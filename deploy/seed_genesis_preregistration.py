#!/usr/bin/env python3
"""seed_genesis_preregistration.py — the genesis pre-registration seeder (#976).

Puts the board ON THE RECORD before Day 1: 1-2 falsifiable opening predictions per
coach (PREDICTION# records, the exact shape /api/predictions reads) plus the cycle's
core falsifiable hypotheses (HYPOTHESIS# records via the hypothesis engine's own
store_hypothesis, so the cross-phase calibration ledger tracks them).

THE FREEZE RULE (pre-registration must not silently change): the first generation
writes every claim to deploy/generated/genesis_preregistration.json. Every later run
— including re-runs after a restart-pipeline wipe — REUSES those frozen claims
verbatim. Regeneration requires deliberately deleting/moving that file.

WIPE WARNING (re-run after the pipeline): COACH#* and HYPOTHESIS# partitions are
EXPERIMENT_SCOPED (ADR-077) — a restart_pipeline.py re-run wipes them. This script
is safely re-runnable afterwards: fixed prediction IDs derived from the frozen
claims mean put_item overwrites, never duplicates, and hypotheses are skipped when
an identically-IDed live row already exists. After any pipeline run, re-run:

    python3 deploy/seed_genesis_preregistration.py --apply

GROUNDING (ADR-104/105): every generated claim is grounded in config/user_goals.json
(targets, milestone schedule, phase plan) and validated deterministically — metric on
the MEASURABLE_METRICS allowlist, resolvable direction, numeric/timeframe content,
confidence attached, eval spec built by coach_state_updater._build_prediction_eval_spec
itself (parity by construction, never a hand-copied shape). Bedrock generation routes
through retry_utils/bedrock_client (ADR-062) and respects budget_guard under the
coach_narrative feature class. If generation fails for a coach, a deterministic
goal-derived fallback prediction (flagged generator=fallback_deterministic) keeps all
8 coaches on the record.

Usage:
    python3 deploy/seed_genesis_preregistration.py            # dry-run (default)
    python3 deploy/seed_genesis_preregistration.py --apply    # write DynamoDB
    python3 deploy/seed_genesis_preregistration.py --skip-hypotheses --apply
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# The reused lambda modules (hypothesis engine, coach state updater) expect their
# runtime env — provide the standard local-script defaults before any import.
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "coach"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp  # noqa: E402  (#1378 — the content-hash seal on the freeze)
from constants import EXPERIMENT_START_DATE  # noqa: E402
from measurable_metrics import MEASURABLE_METRICS, infer_direction, normalize_metric_hint  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
GOALS_PATH = REPO_ROOT / "config" / "user_goals.json"
FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.json"

# The presentation rule (#976): the public artifact may never mention resets, cycles,
# or prior attempts — only /data/cycles/ may know. Enforced on every claim at both
# generation (seeder) and publish (publisher) time.
BANNED_CLAIM_TOKENS = ("cycle", "reset", "restart", "attempt", "last time", "previous experiment", "this time")

# Roster — must match handle_predictions' _pred_coach_id_map (lambdas/web/site_api_coach.py).
COACHES = [
    ("sleep_coach", "Dr. Lisa Park", "sleep"),
    ("nutrition_coach", "Dr. Marcus Webb", "nutrition"),
    ("training_coach", "Dr. Sarah Chen", "training"),
    ("mind_coach", "Dr. Nathan Reeves", "mind / behavior"),
    ("physical_coach", "Dr. Victor Reyes", "physical / body composition"),
    ("glucose_coach", "Dr. Amara Patel", "glucose / metabolic"),
    ("labs_coach", "Dr. James Okafor", "labs / biomarkers"),
    ("explorer_coach", "Dr. Henning Brandt", "exploration / N=1 statistics"),
]

# Subdomain derivation — same substring scan coach_state_updater uses at the write
# boundary, so seeded records bucket identically in the Bayesian confidence model.
_SUBDOMAIN_KEYS = ["sleep", "hrv", "recovery", "weight", "calories", "protein", "glucose", "training", "mood", "stress"]

# Deterministic goal-derived fallbacks (ADR-104: grounded in config/user_goals.json,
# no fabricated numbers) — used only when Bedrock generation fails for a coach.
FALLBACK_PREDICTIONS = {
    "sleep_coach": {
        "claim_natural": (
            "With the 9:00 PM bedtime discipline of the opening plan, average nightly sleep duration "
            "rises toward the 7.5-hour target over the first 14 days."
        ),
        "metric": "sleep_duration_hours",
        "direction": "up",
        "window_days": 14,
        "confidence": "medium",
    },
    "nutrition_coach": {
        "claim_natural": (
            "Holding the 1,500 kcal plan with its 170 g protein floor, daily logged protein trends " "upward over the first 14 days."
        ),
        "metric": "total_protein_g",
        "direction": "up",
        "window_days": 14,
        "confidence": "medium",
    },
    "training_coach": {
        "claim_natural": (
            "With daily 3-mile walks starting Day 1 alongside five gym days a week, daily step count "
            "rises over the first 14 days despite the deliberately reduced week-one lifting volume."
        ),
        "metric": "steps",
        "direction": "up",
        "window_days": 14,
        "confidence": "high",
    },
    "mind_coach": {
        "claim_natural": (
            "The behavioral floor holds through the first two weeks: at least 3 journal entries per "
            "week and no training-frequency collapse below 3 sessions a week."
        ),
        "metric": "",
        "direction": None,
        "window_days": 14,
        "confidence": "medium",
    },
    "physical_coach": {
        "claim_natural": (
            "From the plan's start weight, body weight trends down over the first 14 days — the early move "
            "is primarily water and glycogen, and the plan expects it."
        ),
        "metric": "weight_lbs",
        "direction": "down",
        "window_days": 14,
        "confidence": "high",
    },
    "glucose_coach": {
        "claim_natural": (
            "Under the 1,500 kcal deficit and the 11:30-7:30 eating window, average blood glucose " "declines over the first 21 days."
        ),
        "metric": "blood_glucose_avg",
        "direction": "down",
        "window_days": 21,
        "confidence": "medium",
    },
    "labs_coach": {
        "claim_natural": (
            "With the deficit and daily movement in place, resting heart rate declines from its "
            "starting level over the first 30 days, en route to the 55 bpm target."
        ),
        "metric": "resting_heart_rate",
        "direction": "down",
        "window_days": 30,
        "confidence": "medium",
    },
    "explorer_coach": {
        "claim_natural": (
            "As sleep regularity and daily movement bed in together, 7-day average HRV rises over the "
            "first 30 days toward the 50 ms target."
        ),
        "metric": "hrv_7day_avg",
        "direction": "up",
        "window_days": 30,
        "confidence": "low",
    },
}

WIPE_REMINDER = (
    "REMINDER: coach PREDICTION# and HYPOTHESIS# partitions are EXPERIMENT_SCOPED — a\n"
    "restart_pipeline.py re-run (e.g. Sunday's weigh-in re-anchor) WIPES them. Re-run\n"
    "  python3 deploy/seed_genesis_preregistration.py --apply\n"
    "after the pipeline: the frozen claims in deploy/generated/genesis_preregistration.json\n"
    "are reused verbatim, so the pre-registration re-lands unchanged."
)


# ──────────────────────────────────────────────────────────────────────────────
# Goals digest — the grounding context handed to the generator
# ──────────────────────────────────────────────────────────────────────────────


def load_goals():
    return json.loads(GOALS_PATH.read_text())


def goals_digest(goals):
    """Compact, number-faithful digest of user_goals.json for the generation prompt."""
    t = goals["targets"]
    tl = goals["timeline"]
    milestones = ", ".join(f'{m["lbs"]} lbs ({m["label"]})' for m in t["weight"]["interim_milestones"])
    return (
        f"Start date (Day 1): {tl['start_date']}. Start weight: {tl['start_weight_lbs']} lbs. "
        f"Goal: {t['weight']['goal_lbs']} lbs. Milestone schedule: {milestones}. "
        f"Nutrition: {t['nutrition']['daily_calories_target']} kcal/day target, "
        f"{t['nutrition']['daily_protein_min_g']} g protein floor, "
        f"{t['nutrition']['daily_fiber_min_g']} g fiber minimum, eating window "
        f"{t['nutrition']['eating_window']['window']}. "
        f"Training phase: {t['training']['phases'][0]['phase']} — "
        f"{t['training']['phases'][0]['gym_days_per_week']} gym days/week, "
        f"{t['training']['phases'][0]['structure']}. "
        f"Zone 2 target: {t['training']['zone2_minutes_per_week_target']} min/week. "
        f"Daily movement: {t['training']['daily_movement_target']}. "
        f"Sleep: bed {t['sleep']['target_bedtime']}, wake {t['sleep']['target_wake']}, "
        f"{t['sleep']['target_hours']} h target. "
        f"Biomarker targets: RHR {t['biomarkers']['resting_hr_target_bpm']} bpm, "
        f"HRV {t['biomarkers']['hrv_target_ms']} ms, LDL {t['biomarkers']['ldl_target_mg_dl']} mg/dL. "
        f"Ramp discipline: week 1 reduced volume, no failure sets, no PRs before day 21, "
        f"zone-2 by RPE for the first 2 weeks."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Claim validation (deterministic — ADR-105)
# ──────────────────────────────────────────────────────────────────────────────


def claim_is_clean(claim: str) -> bool:
    """The presentation rule: no reset/cycle/prior-attempt language in a claim."""
    low = (claim or "").lower()
    return not any(tok in low for tok in BANNED_CLAIM_TOKENS)


def validate_prediction(pred: dict) -> list:
    """Deterministic checks on one generated/fallback prediction. Returns issues."""
    issues = []
    claim = (pred.get("claim_natural") or "").strip()
    if len(claim.split()) < 8:
        issues.append("claim_natural too short to be falsifiable")
    if not re.search(r"\d", claim):
        issues.append("claim_natural carries no number/timeframe (ADR-105)")
    if not claim_is_clean(claim):
        issues.append("claim_natural violates the presentation rule (banned token)")
    metric = pred.get("metric") or ""
    if metric and normalize_metric_hint(metric) is None:
        issues.append(f"metric {metric!r} not in MEASURABLE_METRICS")
    if metric and pred.get("direction") not in ("up", "down"):
        issues.append("metric-backed claim needs direction up/down")
    if pred.get("confidence") not in ("low", "medium", "high"):
        issues.append(f"confidence must be low/medium/high, got {pred.get('confidence')!r}")
    try:
        w = int(pred.get("window_days"))
        if not (7 <= w <= 45):
            issues.append(f"window_days must be 7-45, got {w}")
    except (TypeError, ValueError):
        issues.append("window_days must be an integer")
    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Bedrock generation (ADR-062 chokepoint, budget-gated)
# ──────────────────────────────────────────────────────────────────────────────

_GEN_SYSTEM = """You are helping a coaching board go ON THE RECORD the day before a
12-month body-recomposition experiment begins. Each coach states 2 falsifiable opening
predictions about the FIRST WEEKS of the experiment, grounded ONLY in the plan facts
provided. Rules:
- Every claim must name a concrete number or timeframe from the plan and be checkable
  against wearable/log data.
- Choose `metric` ONLY from the allowlist given; if a claim is not machine-measurable,
  set metric to "" (it will be graded qualitatively).
- direction is "up" or "down" (the expected trend of the metric over the window).
- window_days: an integer 7-30.
- confidence: "low", "medium" or "high" — an honest strength-of-belief, not bravado.
- NEVER mention resets, cycles, prior attempts, or that anything came before this plan.
- Do not invent data the plan does not state.
- BOTH predictions must be squarely inside the coach's own named domain — never another
  specialist's metric, never a generic whole-plan claim every coach could make.
- Every number in a claim must appear verbatim in the plan facts, or be simple stated
  arithmetic on them. NEVER estimate a "typical" or assumed baseline (there is no
  baseline data yet — the experiment has not started). A weight claim is anchored to
  the stated start weight; anything else has no known starting value, so predict its
  direction/consistency, not a made-up level.
Respond with ONLY a JSON array (no fence, no prose):
[{"claim_natural": "...", "metric": "...", "direction": "up|down|null",
  "window_days": 14, "confidence": "medium"}, ...]"""


def _live_metric_allowlist():
    """Metrics whose source shows recent data — the #813 write-time liveness gate,
    reused from coach_state_updater so a pre-registered gradable claim can't sit on
    a dead source and stall the public scorecard. Fail-open (all metrics) offline."""
    try:
        from coach_state_updater import _metric_has_recent_data

        cache = {}
        return sorted(m for m in MEASURABLE_METRICS if _metric_has_recent_data(m, cache))
    except Exception as e:
        print(f"  (warn: liveness check unavailable — using full allowlist: {e})")
        return sorted(MEASURABLE_METRICS)


def _claim_tokens(claim: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (claim or "").lower()) if len(w) > 3}


def too_similar(claim: str, accepted: list, threshold: float = 0.55) -> bool:
    """Cross-coach dedup (deterministic): token-set Jaccard vs every accepted claim.
    Eight specialists restating one whole-plan claim is not a board on the record."""
    toks = _claim_tokens(claim)
    if not toks:
        return True
    for other in accepted:
        o = _claim_tokens(other)
        if o and len(toks & o) / len(toks | o) >= threshold:
            return True
    return False


def _parse_json_array(text: str):
    """Parse the model's JSON array, tolerating a ```json fence."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in model output")
    return json.loads(t[start : end + 1])


def generate_predictions_via_bedrock(goals):
    """One Haiku call per coach through the ADR-062 chokepoint. Returns the frozen-file
    coaches dict. Falls back per-coach to FALLBACK_PREDICTIONS on failure."""
    import budget_guard
    from retry_utils import AI_MODEL, call_anthropic_api

    if not budget_guard.allow("coach_narrative"):
        raise SystemExit(
            "budget_guard: coach_narrative is paused at the current budget tier "
            f"(tier {budget_guard.current_tier()}) — pre-registration generation blocked. "
            "Re-run when the tier drops below 2."
        )

    digest = goals_digest(goals)
    allowlist = _live_metric_allowlist()
    print(f"Live-metric allowlist ({len(allowlist)}): {', '.join(allowlist)}")

    coaches_out = {}
    accepted_claims = []
    for coach_id, coach_name, domain in COACHES:
        prompt = (
            f"Coach: {coach_name}, the board's {domain} specialist.\n"
            f"Plan facts (the ONLY ground truth):\n{digest}\n\n"
            f"metric allowlist: {json.dumps(allowlist)}\n\n"
            f"State {coach_name}'s 2 opening predictions — both strictly about {domain} — "
            f"as the JSON array described."
        )
        preds = []
        try:
            raw = call_anthropic_api(
                prompt,
                max_tokens=900,
                system=_GEN_SYSTEM,
                model=AI_MODEL,  # narrative-tier (Sonnet): a one-off, permanent public artifact
                temperature=0.4,
            )
            for cand in _parse_json_array(raw)[:2]:
                cand = {
                    "claim_natural": str(cand.get("claim_natural", "")).strip(),
                    "metric": normalize_metric_hint(str(cand.get("metric") or "")) or "",
                    "direction": cand.get("direction") if cand.get("direction") in ("up", "down") else None,
                    "window_days": cand.get("window_days", 14),
                    "confidence": str(cand.get("confidence", "")).lower(),
                    "generator": "bedrock",
                }
                if cand["metric"] and cand["metric"] not in allowlist:
                    cand["metric"], cand["direction"] = "", None  # #813: dead source → qualitative
                if cand["metric"] and cand["direction"] is None:
                    cand["direction"] = infer_direction(None, cand["claim_natural"])
                issues = validate_prediction(cand)
                if issues:
                    print(f"  {coach_id}: dropped a candidate — {'; '.join(issues)}")
                    continue
                if too_similar(cand["claim_natural"], accepted_claims):
                    print(f"  {coach_id}: dropped a candidate — near-duplicate of an already-accepted claim")
                    continue
                preds.append(cand)
                accepted_claims.append(cand["claim_natural"])
        except Exception as e:
            print(f"  {coach_id}: generation failed ({e})")

        if not preds:
            fb = dict(FALLBACK_PREDICTIONS[coach_id], generator="fallback_deterministic")
            if fb["metric"] and fb["metric"] not in allowlist:
                # #813: never pre-register a gradable claim on a dead source —
                # qualitative is the honest classification.
                fb["metric"], fb["direction"] = "", None
            fb_issues = validate_prediction(fb)
            if fb_issues:  # defensive — fallbacks are tested to be clean
                raise SystemExit(f"{coach_id}: fallback prediction invalid: {fb_issues}")
            preds = [fb]
            print(f"  {coach_id}: using the deterministic goal-derived fallback")
        coaches_out[coach_id] = {"coach_name": coach_name, "predictions": preds}
        print(f"  {coach_id}: {len(preds)} prediction(s) frozen")
    return coaches_out


# ──────────────────────────────────────────────────────────────────────────────
# The frozen file
# ──────────────────────────────────────────────────────────────────────────────


def load_frozen():
    if not FROZEN_PATH.exists():
        return None
    frozen = json.loads(FROZEN_PATH.read_text())
    if frozen.get("genesis") != EXPERIMENT_START_DATE:
        raise SystemExit(
            f"Frozen pre-registration is for genesis {frozen.get('genesis')} but constants say "
            f"{EXPERIMENT_START_DATE}. Pre-registration never silently changes: archive/delete "
            f"{FROZEN_PATH} deliberately to re-generate for the new genesis."
        )
    return frozen


def freeze(coaches_out, hypotheses):
    frozen = {
        "genesis": EXPERIMENT_START_DATE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "FROZEN pre-registration (#976) — never edit; delete deliberately to regenerate.",
        "coaches": coaches_out,
        "hypotheses": hypotheses,
    }
    FROZEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    FROZEN_PATH.write_text(json.dumps(frozen, indent=2) + "\n")
    print(f"FROZE pre-registration → {FROZEN_PATH}")
    # #1378: hash-stamp the freeze the moment it happens — future genesis freezes are
    # content-addressed from birth (stamped_at == freeze time, never backdated).
    genesis_prereg_stamp.write_stamp()
    return frozen


# ──────────────────────────────────────────────────────────────────────────────
# PREDICTION# records — exact handle_predictions shape, eval spec built by the
# coach engine's own builder (parity by construction)
# ──────────────────────────────────────────────────────────────────────────────


def _slug(claim: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", claim.lower()[:40]).strip("_")


def _subdomain_for(metric: str, claim: str) -> str:
    probe = f"{metric} {claim}".lower()
    for key in _SUBDOMAIN_KEYS:
        if key in probe:
            return key
    return "general"


def build_prediction_records(frozen):
    """PREDICTION# items in the exact shape lambdas/web/site_api_coach.handle_predictions
    reads and lambdas/coach/coach_prediction_evaluator.py grades."""
    from coach_state_updater import _build_prediction_eval_spec, _parse_confidence

    created_date = frozen["genesis"]
    date_compact = created_date.replace("-", "")
    records = []
    for coach_id, block in frozen["coaches"].items():
        for pred in block["predictions"]:
            claim = pred["claim_natural"]
            metric = pred.get("metric") or ""
            direction = pred.get("direction") if metric else None
            window = int(pred.get("window_days", 14))
            eval_spec = _build_prediction_eval_spec(metric or None, direction, window)
            pred_id = f"pred_{date_compact}_{_slug(claim)}"
            records.append(
                {
                    "pk": f"COACH#{coach_id}",
                    "sk": f"PREDICTION#{pred_id}",
                    "prediction_id": pred_id,
                    "coach_id": coach_id,
                    "created_date": created_date,
                    "claim_natural": claim,
                    "evaluation": eval_spec,
                    "confidence": _parse_confidence(pred.get("confidence")),
                    "subdomain": _subdomain_for(metric, claim),
                    "confounders_noted": [],
                    "status": "pending",
                    "outcome": None,
                    "outcome_date": None,
                    "outcome_notes": None,
                    "decision_class": "observational",
                    "surfaced_to_subject": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    # Pre-registration provenance — stamped from the FROZEN file so
                    # re-runs after a wipe keep the original on-the-record moment.
                    "pre_registered": True,
                    "pre_registered_at": frozen["generated_at"],
                    "generator": pred.get("generator", "bedrock"),
                }
            )
    return records


# ──────────────────────────────────────────────────────────────────────────────
# HYPOTHESIS# — the cycle's core falsifiable hypotheses (deterministic, goal-derived)
# ──────────────────────────────────────────────────────────────────────────────


def build_hypotheses(goals):
    """The experiment's two core pre-registered hypotheses, grounded in the plan.
    Shapes satisfy hypothesis_engine_lambda.validate_hypothesis (incl. #530 test_spec)."""
    kcal = goals["targets"]["nutrition"]["daily_calories_target"]
    steps_note = goals["targets"]["training"]["daily_movement_target"]
    sw = goals["timeline"]["start_weight_lbs"]  # ADR-104: grounded, never hardcoded (baseline moves per cycle)
    return [
        {
            "hypothesis_id": "genesis_prereg_h1",
            "hypothesis": (
                f"On days when logged calories are at or under the {kcal} kcal plan target, "
                "next-day weight will be lower than after days over target."
            ),
            "domains": ["nutrition", "weight"],
            "evidence": (
                f"Pre-registered at genesis from the plan itself: {kcal} kcal/day target from a "
                f"{sw} lb start (config/user_goals.json); MacroFactor logs daily calories and "
                "Withings logs daily weight, so both arms are directly measurable."
            ),
            "confirmation_criteria": ("Mean next-day weight at least 0.1 lbs lower on adherent days within 30 days, 95% CI excluding 0."),
            "monitoring_window_days": 30,
            "confidence": "high",
            "actionable_if_confirmed": ("Hold the 1,500 kcal baseline through the Foundation phase; escalate only if the trend stalls."),
            "test_spec": {
                "condition_metric": "calories",
                "condition_op": "<=",
                "condition_threshold": kcal,
                "outcome_metric": "weight_lbs",
                "direction": "lower",
                "min_effect": 0.1,
                "lag_days": 1,
            },
        },
        {
            "hypothesis_id": "genesis_prereg_h2",
            "hypothesis": (
                "On days reaching roughly 6,000+ steps (the 3-mile daily-movement floor), "
                "next-day Whoop recovery will be higher than after low-movement days."
            ),
            "domains": ["movement", "recovery"],
            "evidence": (
                f"Pre-registered at genesis from the plan itself: daily movement target '{steps_note}' "
                "(config/user_goals.json); Apple Health logs steps and Whoop logs recovery daily."
            ),
            "confirmation_criteria": ("Next-day recovery at least 3 points higher on 6,000+ step days within 30 days, 95% CI excluding 0."),
            "monitoring_window_days": 30,
            "confidence": "medium",
            "actionable_if_confirmed": ("Protect the daily walk as a recovery lever, not just an energy-expenditure line."),
            "test_spec": {
                "condition_metric": "steps",
                "condition_op": ">=",
                "condition_threshold": 6000,
                "outcome_metric": "recovery",
                "direction": "higher",
                "min_effect": 3,
                "lag_days": 1,
            },
        },
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Writes
# ──────────────────────────────────────────────────────────────────────────────


def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def write_predictions(records):
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    for rec in records:
        table.put_item(Item=_to_decimal(rec))  # fixed sk → overwrite, idempotent
        print(f"WROTE {rec['pk']} / {rec['sk']}")


def write_hypotheses(hypotheses):
    """Store via the hypothesis engine's own writer (pre_registered_at stamped there).
    Idempotent: skips when a live hypothesis with the same hypothesis_id exists."""
    from hypothesis_engine_lambda import load_existing_hypotheses, store_hypothesis, validate_hypothesis

    existing_ids = {h.get("hypothesis_id") for h in load_existing_hypotheses()}
    for hyp in hypotheses:
        ok, issues = validate_hypothesis(hyp)
        if not ok:
            raise SystemExit(f"hypothesis {hyp.get('hypothesis_id')} failed validation: {issues}")
        if hyp["hypothesis_id"] in existing_ids:
            print(f"SKIP hypothesis {hyp['hypothesis_id']} — already live")
            continue
        store_hypothesis(hyp)
        print(f"WROTE hypothesis {hyp['hypothesis_id']}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Seed the genesis pre-registration (#976)")
    ap.add_argument("--apply", action="store_true", help="write DynamoDB (default: dry-run)")
    ap.add_argument("--skip-hypotheses", action="store_true", help="seed only PREDICTION# records")
    args = ap.parse_args()

    goals = load_goals()
    frozen = load_frozen()
    if frozen is None:
        print("No frozen pre-registration found — generating via Bedrock (ADR-062, budget-gated)…")
        coaches_out = generate_predictions_via_bedrock(goals)
        frozen = freeze(coaches_out, build_hypotheses(goals))
    else:
        print(f"Using FROZEN pre-registration from {FROZEN_PATH} (generated {frozen['generated_at']})")
        # #1378: the write path is blocked on a tampered freeze — a hash mismatch
        # means the frozen claims were edited after stamping, and that never ships.
        stamp = genesis_prereg_stamp.require_valid_stamp(frozen)
        print(f"Hash stamp verified: sha256 {stamp['sha256']} (stamped {stamp['stamped_at']})")

    records = build_prediction_records(frozen)
    hypotheses = frozen.get("hypotheses") or build_hypotheses(goals)

    print(f"\nGenesis {frozen['genesis']} — {len(records)} PREDICTION# records across {len(frozen['coaches'])} coaches:")
    for rec in records:
        ev = rec["evaluation"]
        grade = f"{ev['type']}:{ev.get('metric')}:{ev.get('condition')}" if ev.get("metric") else ev["type"]
        print(
            f"  {rec['pk']:24s} {rec['sk']}\n      [{grade} · conf {rec['confidence']} · {ev['evaluation_window_days']}d] "
            f"{rec['claim_natural']}"
        )
    if not args.skip_hypotheses:
        print(f"\n{len(hypotheses)} HYPOTHESIS# record(s):")
        for hyp in hypotheses:
            print(f"  {hyp['hypothesis_id']}: {hyp['hypothesis']}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write DynamoDB.")
        print("\n" + WIPE_REMINDER)
        return 0

    write_predictions(records)
    if not args.skip_hypotheses:
        write_hypotheses(hypotheses)
    print("\n" + WIPE_REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
