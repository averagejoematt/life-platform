#!/usr/bin/env python3
"""
patch_deficit_ceiling.py — Sprint 5, S2-T1-9
Injects the adaptive deficit ceiling (BS-12 / Norton-Attia) into
daily_insight_compute_lambda.py.

What it adds:
  1. _compute_deficit_ceiling_alert() function — two-tier alert:
       Tier A (RATE):   >2.5 lbs/week over 14 days  → P2 signal
       Tier B (MULTI):  HRV -15% AND sleep degraded AND ≥2 T0 failures → P1 signal
  2. Call site in lambda_handler (step 5i)
  3. build_ai_context_block signature update (new param: deficit_ceiling_block)
  4. P1/P2 signal injection in the priority queue
  5. Call in ai_block assembly + return dict flag

Run from project root:
    python3 deploy/patch_deficit_ceiling.py
"""

import re
import os
import sys

LAMBDA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "lambdas", "daily_insight_compute_lambda.py"
)

# ── Guard: idempotency ────────────────────────────────────────────────────────
with open(LAMBDA_PATH, "r", encoding="utf-8") as f:
    original = f.read()

if "_compute_deficit_ceiling_alert" in original:
    print("[SKIP] Deficit ceiling already patched — nothing to do.")
    sys.exit(0)

src = original

# ==============================================================================
# PATCH 1 — Insert the function before build_ai_context_block
# ==============================================================================
DEFICIT_FUNC = '''

# ==============================================================================
# S2-T1-9: ADAPTIVE DEFICIT CEILING  (BS-12 — Norton / Attia / Medical)
# Two-tier alert wired into the Daily Brief:
#   Tier A (RATE):  weight loss >2.5 lbs/week over 14 days
#                   Priority 2 — rate alone is a medical signal (Norton/Attia)
#   Tier B (MULTI): HRV drops >15% from 7d baseline
#                   AND sleep quality degrades (efficiency < 80% for 3+ of last 7d)
#                   AND ≥2 T0 habits failed this week
#                   Priority 1 — multi-signal = physiological cost is real now
#
# Prescription: specific kcal increase + reassessment window, not just a flag.
# Medical disclaimer appended per R13-F09.
# Non-fatal throughout.
# ==============================================================================

# Tier A threshold: >2.5 lbs/week is the hard medical line (Norton/Attia board spec)
DEFICIT_RATE_THRESHOLD_LBS_WEEK  = float(os.environ.get("DEFICIT_RATE_THRESHOLD", "2.5"))
# Tier B thresholds
DEFICIT_HRV_DROP_PCT              = float(os.environ.get("DEFICIT_HRV_DROP_PCT", "0.15"))   # 15%
DEFICIT_SLEEP_EFF_FLOOR           = float(os.environ.get("DEFICIT_SLEEP_EFF_FLOOR", "80.0"))
DEFICIT_SLEEP_BAD_DAYS_GATE       = int(os.environ.get("DEFICIT_SLEEP_BAD_DAYS", "3"))
DEFICIT_T0_FAIL_GATE              = int(os.environ.get("DEFICIT_T0_FAIL_GATE", "2"))
# Prescription params
DEFICIT_KCAL_INCREASE             = int(os.environ.get("DEFICIT_KCAL_INCREASE", "200"))
DEFICIT_REASSESS_DAYS             = int(os.environ.get("DEFICIT_REASSESS_DAYS", "5"))


def _compute_deficit_ceiling_alert(yesterday_str, habit_7d, computed_7d, profile):
    """S2-T1-9: Adaptive deficit ceiling alert.

    Returns (tier, alert_block) where tier is None / "rate" / "multi".
    Non-fatal throughout — returns (None, "") on any failure.
    """
    try:
        today    = datetime.now(timezone.utc).date()
        yest     = datetime.strptime(yesterday_str, "%Y-%m-%d").date()
        wt_start = (yest - timedelta(days=13)).isoformat()  # 14-day window

        # ── Tier A: rate-of-loss check (Withings scale) ──────────────────────
        wt_recs = fetch_range("withings", wt_start, yesterday_str)
        wt_vals = []
        for r in sorted(wt_recs, key=lambda x: x.get("date", "")):
            v = safe_float(r, "weight_lbs")
            if v is not None:
                wt_vals.append(v)

        rate_alert = False
        rate_lbs_week = None
        if len(wt_vals) >= 4:
            # Regression slope over the 14-day window → lbs/day → lbs/week
            slope = _linreg_slope(wt_vals)  # lbs/day (negative = losing)
            if slope is not None:
                rate_lbs_week = abs(slope) * 7  # absolute weekly loss
                if rate_lbs_week > DEFICIT_RATE_THRESHOLD_LBS_WEEK:
                    rate_alert = True

        # ── Tier B: multi-signal check ───────────────────────────────────────
        multi_alert     = False
        hrv_drop_fired  = False
        sleep_fired     = False
        t0_fail_fired   = False

        # HRV: compare 7d recent vs 14d baseline (same as slow_drift logic)
        hrv_baseline_start = (yest - timedelta(days=21)).isoformat()
        hrv_baseline_end   = (yest - timedelta(days=8)).isoformat()
        hrv_recent_start   = (yest - timedelta(days=7)).isoformat()

        hrv_baseline_recs = fetch_range("whoop", hrv_baseline_start, hrv_baseline_end)
        hrv_recent_recs   = fetch_range("whoop", hrv_recent_start, yesterday_str)

        baseline_hrv_vals = [safe_float(r, "hrv") for r in hrv_baseline_recs
                             if safe_float(r, "hrv") is not None]
        recent_hrv_vals   = [safe_float(r, "hrv") for r in hrv_recent_recs
                             if safe_float(r, "hrv") is not None]

        if len(baseline_hrv_vals) >= 7 and len(recent_hrv_vals) >= 3:
            baseline_hrv_mean = sum(baseline_hrv_vals) / len(baseline_hrv_vals)
            recent_hrv_mean   = sum(recent_hrv_vals) / len(recent_hrv_vals)
            if baseline_hrv_mean > 0:
                hrv_drop_pct = (baseline_hrv_mean - recent_hrv_mean) / baseline_hrv_mean
                if hrv_drop_pct >= DEFICIT_HRV_DROP_PCT:
                    hrv_drop_fired = True

        # Sleep efficiency: count days <80% in last 7d
        sleep_eff_vals = []
        for r in hrv_recent_recs:
            v = safe_float(r, "sleep_efficiency_percentage")
            if v is not None:
                sleep_eff_vals.append(v)
        bad_sleep_days = sum(1 for v in sleep_eff_vals if v < DEFICIT_SLEEP_EFF_FLOOR)
        if bad_sleep_days >= DEFICIT_SLEEP_BAD_DAYS_GATE:
            sleep_fired = True

        # T0 habits: count distinct T0 failures this week
        if habit_7d:
            sorted_habits = sorted(habit_7d, key=lambda x: x.get("date", ""))
            recent_habits = sorted_habits[-7:]
            all_missed = []
            for r in recent_habits:
                all_missed.extend(r.get("missed_tier0") or [])
            unique_failed = len(set(all_missed))
            if unique_failed >= DEFICIT_T0_FAIL_GATE:
                t0_fail_fired = True

        multi_channels = sum([hrv_drop_fired, sleep_fired, t0_fail_fired])
        if multi_channels >= 2:
            multi_alert = True

        # ── Neither tier fired → clean return ────────────────────────────────
        if not rate_alert and not multi_alert:
            logger.info(
                "S2-T1-9: No deficit ceiling alert (rate=%.2f lbs/wk, multi_channels=%d/%d)",
                rate_lbs_week or 0, multi_channels, 3
            )
            return None, ""

        # ── Build prescription ────────────────────────────────────────────────
        cal_target     = profile.get("calorie_target", 1800)
        new_ceiling    = cal_target + DEFICIT_KCAL_INCREASE
        prot_target    = profile.get("protein_target_g", 190)

        rate_str = f"{rate_lbs_week:.1f} lbs/wk" if rate_lbs_week else "unknown"

        if multi_alert:
            tier = "multi"
            headline = "\U0001f6a8 DEFICIT CEILING BREACHED — MULTI-SIGNAL (BS-12)"
            channels_desc = ", ".join([
                x for x, fired in [
                    ("HRV ↓ >15%",               hrv_drop_fired),
                    (f"sleep eff <{int(DEFICIT_SLEEP_EFF_FLOOR)}% ({bad_sleep_days}+ days)", sleep_fired),
                    (f"{unique_failed if t0_fail_fired else '?'} T0 habits failing",            t0_fail_fired),
                ] if fired
            ])
            body = (
                f"  {channels_desc}\n"
                f"  Weight rate: {rate_str}"
            )
        else:
            tier = "rate"
            headline = f"\u26a0\ufe0f DEFICIT RATE ALERT (S2-T1-9): {rate_str} loss — threshold >{DEFICIT_RATE_THRESHOLD_LBS_WEEK} lbs/wk"
            body = f"  Weight loss rate exceeds safe threshold for lean tissue preservation."

        prescription = (
            f"  PRESCRIPTION: Increase daily calorie target by {DEFICIT_KCAL_INCREASE} kcal for "
            f"{DEFICIT_REASSESS_DAYS} days ({cal_target} → {new_ceiling} kcal/day). "
            f"Maintain protein at {prot_target}g. Reassess trend at day {DEFICIT_REASSESS_DAYS}."
        )

        instruction = (
            "INSTRUCTION: Name this directly and prescribe the specific calorie adjustment above. "
            "Do NOT soften with vague language like 'consider eating more'. "
            "Norton: lean tissue loss at this rate is irreversible on a fat-loss timeline. "
            "Attia: the goal is fat loss, not weight loss — protect the muscle. "
            "Give the exact number: increase to {new_ceiling} kcal/day for {reassess} days.".format(
                new_ceiling=new_ceiling, reassess=DEFICIT_REASSESS_DAYS
            )
        )

        disclaimer = "  _For personal tracking only. Consult a qualified healthcare provider for medical decisions._"

        alert_block = "\n".join([headline, body, prescription, instruction, disclaimer])

        logger.warning(
            "S2-T1-9: Deficit ceiling alert FIRED — tier=%s, rate=%.2f lbs/wk, "
            "hrv_drop=%s, sleep=%s, t0_fail=%s",
            tier, rate_lbs_week or 0, hrv_drop_fired, sleep_fired, t0_fail_fired
        )
        return tier, alert_block

    except Exception as e:
        logger.warning("S2-T1-9 deficit ceiling check failed (non-fatal): %s", e)
        return None, ""

'''

ANCHOR_FUNC = "# ==============================================================================\n# AI CONTEXT BLOCK ASSEMBLER  (priority queue version — IC-19 v1.3.0)"
src = src.replace(ANCHOR_FUNC, DEFICIT_FUNC + ANCHOR_FUNC, 1)

# ==============================================================================
# PATCH 2 — Update build_ai_context_block signature
# ==============================================================================
OLD_SIG = "def build_ai_context_block(momentum_signal, this_week_avg, prev_week_avg, trend_pct,\n                            declining, improving, miss_rates, strongest, weakest,\n                            synergy_health, memory_ctx, intention_gap_ctx=\"\",\n                            early_warning_block=\"\",\n                            slow_drift_metrics=None,\n                            experiment_ctx=\"\",\n                            social_flag=\"\",\n                            decision_fatigue_block=\"\",\n                            acwr_signal=None):"
NEW_SIG = "def build_ai_context_block(momentum_signal, this_week_avg, prev_week_avg, trend_pct,\n                            declining, improving, miss_rates, strongest, weakest,\n                            synergy_health, memory_ctx, intention_gap_ctx=\"\",\n                            early_warning_block=\"\",\n                            slow_drift_metrics=None,\n                            experiment_ctx=\"\",\n                            social_flag=\"\",\n                            decision_fatigue_block=\"\",\n                            acwr_signal=None,\n                            deficit_ceiling_block=\"\",\n                            deficit_ceiling_tier=None):"
src = src.replace(OLD_SIG, NEW_SIG, 1)

# ==============================================================================
# PATCH 3 — Inject deficit ceiling signals into priority queue
# (After P1 early_warning, before P2 severe slow drift)
# ==============================================================================
OLD_P2 = "    # P2: Severe slow drift (displaces lower signals — Attia/Henning)"
NEW_P2 = """    # P1b: S2-T1-9 Multi-signal deficit ceiling (always surfaces — physiological cost is real)
    if deficit_ceiling_block and deficit_ceiling_tier == "multi":
        signals.append({"priority": 1, "content": deficit_ceiling_block, "token_estimate": 70})

    # P2b: Rate-only deficit ceiling (elevated priority — medical threshold exceeded)
    if deficit_ceiling_block and deficit_ceiling_tier == "rate":
        signals.append({"priority": 2, "content": deficit_ceiling_block, "token_estimate": 55})

    # P2: Severe slow drift (displaces lower signals — Attia/Henning)"""
src = src.replace(OLD_P2, NEW_P2, 1)

# ==============================================================================
# PATCH 4 — Call site in lambda_handler (after 5h ACWR block)
# ==============================================================================
OLD_5H_END = "    # ── 6. Assemble AI context block ──"
NEW_5H_END = """    # ── 5i. S2-T1-9: Adaptive Deficit Ceiling Alert (non-fatal) ──────────────────
    deficit_ceiling_tier, deficit_ceiling_block = None, ""
    try:
        deficit_ceiling_tier, deficit_ceiling_block = _compute_deficit_ceiling_alert(
            yesterday_str, habit_7d, computed_7d, profile
        )
        if deficit_ceiling_tier:
            logger.warning("S2-T1-9: Deficit ceiling alert tier=%s fired for %s",
                           deficit_ceiling_tier, yesterday_str)
    except Exception as e:
        logger.warning("S2-T1-9 deficit ceiling failed (non-fatal): %s", e)

    # ── 6. Assemble AI context block ──"""
src = src.replace(OLD_5H_END, NEW_5H_END, 1)

# ==============================================================================
# PATCH 5 — Pass new args into build_ai_context_block call
# ==============================================================================
OLD_CALL = "        decision_fatigue_block=decision_fatigue_block,\n        acwr_signal=acwr_signal)"
NEW_CALL = "        decision_fatigue_block=decision_fatigue_block,\n        acwr_signal=acwr_signal,\n        deficit_ceiling_block=deficit_ceiling_block,\n        deficit_ceiling_tier=deficit_ceiling_tier)"
src = src.replace(OLD_CALL, NEW_CALL, 1)

# ==============================================================================
# PATCH 6 — Add to return dict
# ==============================================================================
OLD_RETURN = '        "decision_fatigue_fired": df_fired,\n    }'
NEW_RETURN = '        "decision_fatigue_fired": df_fired,\n        "deficit_ceiling_tier": deficit_ceiling_tier,\n    }'
src = src.replace(OLD_RETURN, NEW_RETURN, 1)

# ==============================================================================
# Write patched file
# ==============================================================================
if "_compute_deficit_ceiling_alert" not in src:
    print("[ERROR] Patch 1 failed — anchor text not found. No changes written.")
    sys.exit(1)
if "deficit_ceiling_tier=None" not in src:
    print("[ERROR] Patch 2 failed — signature anchor not found. No changes written.")
    sys.exit(1)

with open(LAMBDA_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("=== patch_deficit_ceiling.py complete ===")
print()
print("Patches applied:")
print("  1. _compute_deficit_ceiling_alert() function added")
print("  2. build_ai_context_block() signature updated")
print("  3. P1/P2 signals injected into priority queue")
print("  4. lambda_handler step 5i call site added")
print("  5. build_ai_context_block call updated")
print("  6. return dict updated (deficit_ceiling_tier)")
print()
print("Next: deploy the daily-brief Lambda")
print("  bash deploy/deploy_lambda.sh daily-insight-compute")
