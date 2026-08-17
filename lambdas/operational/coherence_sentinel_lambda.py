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
from typing import TYPE_CHECKING

import boto3
from boto3.dynamodb.conditions import Key

try:
    from common.platform_logger import get_logger

    logger = get_logger("coherence-sentinel")
except ImportError:
    logger = logging.getLogger("coherence-sentinel")
    logger.setLevel(logging.INFO)

from experiment import coherence_invariants as ci  # bundled shared module (pure cores)

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

# All three rosters below are derived from the canonical persona registry, never
# re-typed (#2334; guard: tests/test_coach_roster_set_guard_2334.py) — this file
# held THREE hand-typed copies, two of them in different orders.
from coach.persona_registry import OPERATIONAL_COACH_IDS, OPERATIONAL_SHORT_IDS

COACH_IDS = list(OPERATIONAL_COACH_IDS)
EXPERTS = list(OPERATIONAL_SHORT_IDS)
# ADR-104: the V2 operational coaches whose served OUTPUT# narratives the facts
# pass now also covers (matches coach_narrative_orchestrator.ALL_COACH_IDS).
V2_COACHES = list(OPERATIONAL_COACH_IDS)

try:
    from experiment.phase_filter import with_phase_filter
except ImportError:  # pragma: no cover
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def with_phase_filter(kwargs, include_pilot=False):
            return kwargs


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _decimal(o):
    try:
        from common.numeric import decimals_to_float

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


def _facts_from_cm(cm):
    """Build the sentinel's facts dict from ONE computed_metrics record.

    Facts come from `canonical_facts.build_canonical_facts` — the SAME schema the
    coaches are grounded on (ai_expert_analyzer._load_canonical_facts). That closes
    the grounding↔detection loop: the Sentinel checks served narratives against the
    exact extraction the coaches were handed, and the semantic pass now sees the
    protein avg/target/floor distinctly (the 140/170/190 confusion it flagged live).
    Fail-soft to the 4 invariant-required fields if the module isn't importable."""
    try:
        from experiment.canonical_facts import build_canonical_facts

        facts = {k: v for k, v in build_canonical_facts(cm).items() if k != "as_of"}
    except Exception:  # noqa: BLE001 — bundled module; degrade to the core 4

        def _f(k):
            v = cm.get(k)
            try:
                return round(float(v), 1) if v is not None else None
            except (TypeError, ValueError):
                return None

        facts = {k: _f(k) for k in ("recovery_pct", "hrv_ms", "rhr_bpm", "latest_weight")}
    # M-8 (#493 / ADR-109): TSB is a DERIVED value, deliberately NOT in the canonical_facts
    # schema (that stays scoped to measured vitals + weight, which the tight grounding_guard
    # reads and injects into coach prompts). Supply it to the SENTINEL facts directly from
    # computed_metrics so the scheduled cross-surface scan covers the coach-context TSB line.
    # The wide absolute tolerance lives in coherence_invariants._ABS_TOL.
    _tsb = cm.get("tsb")
    try:
        facts["tsb"] = round(float(_tsb), 1) if _tsb is not None else None
    except (TypeError, ValueError):
        facts["tsb"] = None
    return facts


def _facts_as_of_generation(out_date):
    """The computed_metrics record a coach generated on ``out_date`` was grounded on.

    computed_metrics computes COMPLETED days: at the 17:00Z brief on day D the newest
    record is DATE#(D-1), so a narrative dated D cites D-1's vitals. When an ADR-108
    hold serves that narrative on D+1, `_latest` has advanced and the citations read
    as contradictions (#2792's live false-ALARM). Returns the latest record strictly
    BEFORE out_date, or {} (fail-soft — caller then checks against today's facts,
    the pre-#2792 behaviour: absence can only make the check stricter, never blind)."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}computed_metrics") & Key("sk").lt(f"DATE#{out_date}"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = _decimal(resp.get("Items", []))
        return _facts_from_cm(items[0]) if items else {}
    except Exception:  # noqa: BLE001
        return {}


def _gather_facts_and_narratives():
    """Canonical facts (computed_metrics) + the day's served narratives.

    Returns ``(facts, narratives, labels, facts_overrides)`` — the overrides map a
    stale-served coach label to the facts of ITS OWN generation day (#2792), so a
    held narrative is judged like-for-like instead of against facts it never saw."""
    facts = _facts_from_cm(_latest("computed_metrics"))
    narratives, labels = [], []
    facts_overrides = {}
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
    # ADR-104: the V2 operational-coach narratives (daily brief) — previously the
    # highest-traffic coach surface with NO Sentinel coverage. Latest OUTPUT# per
    # coach, but only if served today/yesterday: the facts are the LATEST record,
    # so checking an old narrative against new facts would manufacture false
    # contradictions (the day-boundary-skew lesson).
    _now = datetime.now(timezone.utc)
    _fresh_floor = (_now - timedelta(days=1)).strftime("%Y-%m-%d")
    _today = _now.strftime("%Y-%m-%d")
    _own_day_cache: dict = {}
    for coach_id in V2_COACHES:
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#"),
                ScanIndexForward=False,
                Limit=1,
            )
            items = resp.get("Items", [])
        except Exception:  # noqa: BLE001
            items = []
        if items:
            item = _decimal(items[0])
            _out_date = str(item.get("sk", ""))[7:17]  # OUTPUT#YYYY-MM-DD#...
            txt = str(item.get("content") or "")
            if txt.strip() and _out_date >= _fresh_floor:
                narratives.append(txt)
                labels.append(f"coach:{coach_id}")
                # #2792: a row dated before today is being SERVED STALE (ADR-108 hold
                # or a skipped generation kept yesterday's narrative live). Judge it
                # against the facts of its own generation day, not today's.
                if _out_date < _today:
                    if _out_date not in _own_day_cache:
                        _own_day_cache[_out_date] = _facts_as_of_generation(_out_date)
                    if _own_day_cache[_out_date]:
                        facts_overrides[f"coach:{coach_id}"] = {"facts": _own_day_cache[_out_date], "as_of": _out_date}
    return facts, narratives, labels, facts_overrides


def _gather_computed_checks():
    """Cheap internal-coherence checks that need no engine: a stored value must
    agree with what its OWN sibling fields imply. Catches a stored/derived desync.

    #2736 — this adapter read `score` and `grade`; the record has stored
    `total_score` and `letter_grade` since the OLDEST row in the partition
    (DATE#2023-07-23). The guard was therefore never true, `checks` was always
    `[]`, and an empty list has no offenders — so invariant 2 reported OK, daily,
    having examined nothing, for the life of the file. Field names below are taken
    from a live item, not from a fixture.

    Coverage against what the compute Lambdas actually store (checked 2026-08-15):
      · day_grade      — COVERED (letter vs its own score, via the engine's
                          letter_grade, so the band table is never re-typed here — #2793)
      · character_sheet — COVERED (tier vs its own level, via the engine's get_tier,
                          so the band table is never re-typed here)
      · adaptive_mode  — not covered: `mode_label` is chosen by a policy, not derived
                          from `component_scores`, so there is no arithmetic identity
                          to assert without duplicating the policy
      · readiness      — not covered: no `SOURCE#readiness` partition exists
      · character_receipt — not covered: it already carries `replay_verified`, its own
                          stronger self-check; asserting it here would be a second copy
    """
    checks = []
    dg = _latest("day_grade")
    score = dg.get("total_score") if isinstance(dg, dict) else None
    letter = (dg or {}).get("letter_grade")
    if score is not None and letter:
        try:
            # #2793: derive the expected letter from the ENGINE's own mapping — never a
            # re-typed band table. This block used to hand-type "collegiate" bands
            # (90/A 80/B 70/C 60/D) claiming they "match scoring_engine bands"; the
            # engine's real curve (A- down to 85, B- down to 70, C- down to 55, D=45-54,
            # F<45) disagrees at first-letter level for every score in 45-89 except
            # 80-84. The first stored row in the disagreement range (DATE#2026-08-15,
            # total_score 51, letter D — engine-coherent) tripped the 2026-08-16 18:45Z
            # run: the instrument's copy had drifted, not the stored record. Same
            # single-source pattern as get_tier below (charter standing rule 1); the
            # comparison stays tol 0 and is now the FULL letter, modifiers included,
            # since the stored letter comes from this exact function at store time.
            from health.scoring_engine import letter_grade

            derived = letter_grade(float(score))
            stored_letter = str(letter).strip()
            checks.append(
                {
                    # The letters ride in the name so an alarm reads as letters — the
                    # old ord() encoding printed "stored 68 vs derived 70" and sent
                    # #2793 hunting a 2-point score bug that never existed.
                    "name": f"day_grade_letter_vs_score[{stored_letter} vs {derived}]",
                    "stored": float(stored_letter == derived),
                    "expected": 1.0,
                    "tol": 0,
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("coherence: day-grade letter check unavailable: %s", e)
    cs = _latest("character_sheet")
    level = cs.get("character_level") if isinstance(cs, dict) else None
    tier = (cs or {}).get("character_tier")
    if level is not None and tier:
        try:
            from health.character_engine import get_tier

            expected_tier = str((get_tier(int(float(level))) or {}).get("name") or "")
            if expected_tier:
                checks.append(
                    {
                        "name": "character_tier_vs_level",
                        "stored": float(str(tier).strip().lower() == expected_tier.strip().lower()),
                        "expected": 1.0,
                        "tol": 0,
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("coherence: character tier check unavailable: %s", e)
    return checks


def _experiment_age_days():
    """Days since EXPERIMENT_START_DATE, or None if genesis is unknown/unparsable
    (BUG-05, #379). Feeds check_endpoint_shape's post-reset grace window so a
    board that's legitimately empty in the first days of a new cycle doesn't
    read as the handle_predictions degenerate-payload outage. Fail-soft: a
    missing genesis just disables the gate (original ungated behavior)."""
    try:
        from common import constants

        genesis = constants.EXPERIMENT_START_DATE
    except Exception:  # noqa: BLE001
        genesis = os.environ.get("EXPERIMENT_START_DATE")
    if not genesis:
        return None
    try:
        g = datetime.strptime(str(genesis)[:10], "%Y-%m-%d").date()
        return (datetime.now(timezone.utc).date() - g).days
    except (ValueError, TypeError):
        return None


def _gather_endpoint_specs():
    """Key endpoints + the non-degenerate shape each must satisfy.

    `behavioral_sources` (#2735) names the sources whose SILENCE would legitimately
    empty this endpoint. It is a per-endpoint fact (only the endpoint's author knows
    what feeds it) — but whether a named source actually counts as behavioural is
    NOT asserted here: `_quiet_behavioral_sources` intersects these keys with
    `source_registry.behavioral_source_keys()`, so a source reclassified to
    infrastructure stops excusing an empty payload without anyone editing this list.

    All four specs were checked against live payloads (2026-08-15), not presumed:
      · nutrition_overview — macrofactor. The whole non_degenerate set is nutrition
        logging, so a logging lapse empties it completely. This is the live case.
      · vitals           — withings backs the weight_* fields, but non_degenerate is
        the whole `vitals` object and whoop (infrastructure) keeps hrv/rhr populated,
        so a skipped weigh-in alone can never degenerate it. Listed anyway: correct
        today by accident of the spec's breadth, and free to name.
      · predictions, coaching_dashboard — intelligence-layer outputs with no
        behavioural writer. Deliberately empty: an empty board there IS the outage.
    """
    return [
        (
            "predictions",
            "/api/predictions",
            {"required": ["overall.total"], "non_degenerate": ["overall.total", "predictions"], "behavioral_sources": []},
        ),
        (
            "nutrition_overview",
            "/api/nutrition_overview",
            {
                "required": ["nutrition"],
                "non_degenerate": ["nutrition.avg_calories", "nutrition.days_logged"],
                "behavioral_sources": ["macrofactor"],
            },
        ),
        (
            "coaching_dashboard",
            "/api/coaching-dashboard",
            {"required": ["coaches"], "non_degenerate": ["coaches"], "behavioral_sources": []},
        ),
        ("vitals", "/api/vitals", {"required": ["vitals"], "non_degenerate": ["vitals"], "behavioral_sources": ["withings"]}),
    ]


def _quiet_behavioral_sources(keys):
    """[{key,label,last_date,days}] for each named source that is BOTH classified
    behavioural in the registry AND silent past its own `stale_hours` cadence.

    Both halves are derived, never hand-typed: `behavioral_source_keys()` owns the
    classification and the `stale_hours` facet owns the threshold. #2326 is explicit
    that these facets are canonical and must not be re-stated or re-tuned here.
    Fail-soft: if the registry or DDB can't be read we return nothing, which restores
    the old ALARM behaviour rather than silently excusing an empty payload.
    """
    if not keys:
        return []
    try:
        from ingestion.source_registry import QUIET_NOTICE_MIN_DAYS, SOURCE_REGISTRY, behavioral_source_keys

        behavioral = behavioral_source_keys()
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: source registry unavailable, no behavioural excuse: %s", e)
        return []
    out = []
    today = datetime.now(timezone.utc).date()
    for key in keys:
        if key not in behavioral:
            continue
        facets = SOURCE_REGISTRY.get(key) or {}
        try:
            latest = _latest(key)
        except Exception as e:  # noqa: BLE001
            logger.warning("coherence: latest(%s) failed: %s", key, e)
            continue
        sk = str((latest or {}).get("sk") or "")
        if not sk.startswith("DATE#"):
            continue
        last_date = sk[5:15]
        try:
            days = (today - datetime.strptime(last_date, "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            continue
        stale_hours = facets.get("stale_hours")
        # No stale_hours facet (strava) means no declared cadence — fall back to the
        # registry's own quiet floor rather than inventing a number here.
        threshold_days = (float(stale_hours) / 24.0) if stale_hours else float(QUIET_NOTICE_MIN_DAYS)
        if days > threshold_days:
            out.append({"key": key, "label": facets.get("label") or key, "last_date": last_date, "days": days})
    return out


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


def _gather_experiment_continuity():
    """SS-05: genesis date + today + the experiment week numbers actually surfaced to
    readers. The experiment runs CONTINUOUSLY (a reset is a manual restart_pipeline.py
    act), so this only flags a counter that DISAGREES with genesis — the ADR-077 stale-
    pre-reset leak (a high week number resurfacing) or a misconfigured genesis. Fail-soft."""
    genesis = None
    try:
        from common import constants

        genesis = constants.EXPERIMENT_START_DATE
    except Exception:  # noqa: BLE001
        genesis = os.environ.get("EXPERIMENT_START_DATE")
    surfaced = []
    try:
        arc = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#experiment_arc"}).get("Item")
        if arc:
            wc = _decimal(arc).get("week_count")
            if wc:
                surfaced.append({"name": "experiment_arc_week_count", "week": wc})
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: arc week_count read failed: %s", e)
    # The latest published chronicle week (the serial's current installment).
    try:
        idx = _get_json("/api/journey_timeline") or {}
        weeks = [e.get("week") for e in (idx.get("entries") or idx.get("posts") or []) if e.get("week")]
        if weeks:
            surfaced.append({"name": "latest_chronicle_week", "week": max(int(w) for w in weeks)})
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: chronicle week read failed: %s", e)
    return genesis, _today(), surfaced


# ── Semantic pass (budget-gated Claude) ──────────────────────────────────────
def _semantic_pass(facts, narratives):
    """A Haiku read on whether the served narratives cohere with the facts —
    the content analogue of the visual AI-QA. Budget-gated; fail-soft."""
    try:
        from ai import budget_guard

        if not budget_guard.allow("coherence_semantic"):
            return None
    except Exception:  # noqa: BLE001
        return None  # no budget guard → stay deterministic
    if not narratives:
        return None
    try:
        from ai import bedrock_client

        facts_line = "; ".join(f"{k}={v}" for k, v in facts.items() if v is not None)
        joined = "\n\n".join(n[:600] for n in narratives[:8])
        prompt = (
            "You are a QA auditor for an AI health platform. Below are the authoritative facts for the day, "
            "then several coach narratives served to the user. Flag ONLY a HARD, unambiguous incoherence: "
            "a narrative stating a number that clearly contradicts a fact (off by MORE than 25%), a direct "
            "self-contradiction between narratives, or a unit error (HRV is milliseconds, not bpm). "
            "Do NOT flag any of the following — these are NOT incoherence: a metric simply not being mentioned; "
            "a number within ~25% of the fact (normal day-to-day variance); a cumulative total vs a weekly rate "
            "(e.g. 'lost 13.8 lbs' alongside a -7.3 lb/week rate — different framings, both can be true); a "
            "historical or trend value cited alongside the current one. When unsure, treat it as coherent. "
            "Ignore tone/style. Respond with strict JSON: "
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

    facts, narratives, labels, facts_overrides = _gather_facts_and_narratives()
    findings.append(ci.check_facts_agreement(narratives, facts, surfaces=labels, facts_overrides=facts_overrides))

    findings.append(ci.check_computed_coherence(_gather_computed_checks()))

    age_days = _experiment_age_days()
    for name, path, spec in _gather_endpoint_specs():
        payload = _get_json(path)
        if payload is None:
            f = ci.Finding(f"endpoint_shape:{name}", ci.WARN, 1.0, f"{name}: endpoint unreachable")
        else:
            quiet = _quiet_behavioral_sources(spec.get("behavioral_sources"))
            f = ci.check_endpoint_shape(name, payload, spec, experiment_age_days=age_days, quiet_sources=quiet)
        findings.append(f)

    findings.append(ci.check_count_agreement(_gather_counts()))

    genesis, today, surfaced_weeks = _gather_experiment_continuity()
    if genesis:
        findings.append(ci.check_experiment_continuity(genesis, today, surfaced_weeks))

    semantic = _semantic_pass(facts, narratives)
    return findings, semantic


def _digest(findings, semantic):
    worst = ci.overall_status(findings)
    lines = [f"COHERENCE SENTINEL — {worst.upper()} ({_today()})", ""]
    for f in findings:
        mark = {"ok": "🟢", "pre_start": "⏳", "warn": "🟡", "alarm": "🔴"}.get(f.status, "·")
        lines.append(f"{mark} {f.name}: {f.detail}")
    if semantic is not None:
        sc = "🟢 coherent" if semantic.get("coherent") else "🔴 incoherent"
        lines.append("")
        lines.append(f"AI semantic read: {sc}")
        for issue in (semantic.get("issues") or [])[:5]:
            lines.append(f"   · {issue}")
    return "\n".join(lines)


def _emit_overall(worst, semantic):
    """A single dimensionless gauge the alarm watches: 1 when a DETERMINISTIC invariant
    is ALARM. The Haiku semantic pass is ADVISORY only — it lists confirmations as
    "issues" and flips `coherent` false on borderline variance, so letting it drive a
    daily-emailing CloudWatch alarm makes the alarm permanently red = ignored. The
    deterministic invariants now cover the egregious numeric contradictions (RHR/HRV/
    recovery/weight with grounding-aware precision); the semantic read stays in the
    digest + record for a human/agent to weigh, but doesn't trip the alarm alone."""
    val = 1.0 if worst == ci.ALARM else 0.0
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

    `status` MIRRORS the coherence-overall alarm (see _emit_overall): the DETERMINISTIC
    invariant verdict drives it, so the agent triages a precise signal. `semantic_incoherent`
    is kept as an ADVISORY flag (the Haiku read is too noisy to alarm on — it lists
    confirmations as issues), surfaced in the digest/record for a human to weigh."""
    semantic_bad = bool(semantic and semantic.get("coherent") is False)
    status = worst
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
