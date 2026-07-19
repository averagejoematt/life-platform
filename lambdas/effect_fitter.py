"""
effect_fitter.py — fitted, not authored: cross-pillar effects earn their status
from data (#1411, ADR-105).

The character engine's cross-pillar effects (Sleep Drag, Training Boost, Synergy
Bonus, …) are authored config multipliers — narrative-shaped priors. This module
is the fitting step they never had: each effect is tested as lagged driver→target
pairs over the stored daily pillar scores, with

  * a moving-block bootstrap 95% CI on the lagged Pearson r (stats_core — the one
    sanctioned implementation, preserves short-range autocorrelation),
  * BH-FDR across the whole effect family (multiple-comparisons honesty),
  * n_eff from the autocorrelation-corrected effective sample size,
  * a direction requirement: every authored effect claims a POSITIVE lagged
    driver→target association (a "boost" says high driver lifts tomorrow's
    target; a "drag" gated on a LOW driver says the same association from the
    other end), so a confident wrong-sign fit can never confirm the prior.

Verdicts (per effect, rolled up over its target pairs — ALL pairs must confirm):

  fitted          — CI excludes the null on the authored side, survives BH-FDR,
                    n_eff ≥ MIN_N_EFF. Earned only here, never hand-written.
  authored-prior  — everything else, with an honest reason:
                    insufficient_n / null_not_excluded / sign_mismatch.

Deterministic end to end (fixed bootstrap seed, no LLM anywhere — ADR-105 rule:
deterministic computation before any narrative). Status moves in BOTH directions:
every quarterly re-fit recomputes from scratch, so a fitted effect that stops
holding reverts to authored-prior.

Storage: pk = USER#{user}#SOURCE#effect_fits, sk = FIT#YYYY-MM-DD — classified
CROSS_PHASE in phase_taxonomy (the fits measure the PLATFORM's priors across the
whole history, not one cycle). Consumers: character_sheet_lambda merges the
latest fit into the engine config (badges on active effects), /api/character_config
serves it to the character sheet, /api/wrong publishes the null fits.
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from boto3.dynamodb.conditions import Key
from numeric import floats_to_decimal  # bundled shared module (#1207)
from stats_core import (
    bh_fdr,
    effective_sample_size,
    moving_block_bootstrap_ci,
    pearson_p_value,
    pearson_r,
)

logger = logging.getLogger(__name__)

STATUS_FITTED = "fitted"
STATUS_AUTHORED = "authored-prior"

# The n_eff floor before a verdict is anything but "not yet tested". 20 effective
# days ≈ the confidence grammar's HIGH threshold (charts.js / correlation_evidence
# use 21) — below it the CI is too wide to mean anything either way.
MIN_N_EFF = 20.0
ALPHA = 0.05  # BH-FDR q threshold, matched to the 95% CI
LAG_DAYS = 1  # driver day t → target day t+1 (lagged, not same-day, by design)
FIT_WINDOW_DAYS = 365  # most recent history the fit reads
REFIT_INTERVAL_DAYS = 90  # quarterly, piggybacked on the weekly hypothesis cron
FIT_SK_PREFIX = "FIT#"

PILLAR_NAMES = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")

_COND_TERM = re.compile(r"^\s*(\w+)\s*(<=|>=|<|>|==|!=)\s*([\d.]+)\s*$")


def effect_fits_pk(user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#effect_fits"


# ══════════════════════════════════════════════════════════════════════════════
# SPEC DERIVATION — the pairs to test come FROM the config, never a second list
# ══════════════════════════════════════════════════════════════════════════════
def _condition_drivers(condition: str) -> dict[str, Any]:
    """Derive the driver from an effect's condition string.

    kinds: "pillars" (min over the named pillars — a conjunction's binding
    constraint), "all_pillars" (min over every pillar that day), "vice_streak"
    (max tracked streak — no per-day driver in the sheet partition, so this
    honestly fits n=0 until one is stored).
    """
    terms = [t.strip() for t in (condition or "").split(" AND ") if t.strip()]
    pillars = []
    kind = "pillars"
    for t in terms:
        m = _COND_TERM.match(t)
        if not m:
            continue
        name = m.group(1)
        if name == "all_pillars":
            kind = "all_pillars"
        elif name == "any_vice_streak":
            kind = "vice_streak"
        elif name in PILLAR_NAMES:
            pillars.append(name)
    return {"kind": kind, "pillars": pillars}


def derive_fit_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """One lagged-pair test per (effect, target). Every effect's authored claim
    is a positive lagged association (see module docstring)."""
    specs = []
    for effect in config.get("cross_pillar_effects", []) or []:
        drivers = _condition_drivers(effect.get("condition", ""))
        for target in effect.get("targets") or {}:
            specs.append(
                {
                    "effect": effect.get("name", ""),
                    "drivers": drivers,
                    "target": target,
                    "lag_days": LAG_DAYS,
                    "expected_sign": 1,
                }
            )
    return specs


# ══════════════════════════════════════════════════════════════════════════════
# SERIES EXTRACTION — from stored daily character_sheet records
# ══════════════════════════════════════════════════════════════════════════════
def _raw_score(rec: dict, pillar: str) -> Optional[float]:
    pd = rec.get(f"pillar_{pillar}")
    if not isinstance(pd, dict):
        return None
    v = pd.get("raw_score")
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # A never-instrumented placeholder is a neutral 50 the day never measured —
    # excluding it keeps the fit on real readings (ADR-104 honesty).
    if pd.get("not_instrumented"):
        return None
    return f


def _driver_value(rec: dict, drivers: dict[str, Any]) -> Optional[float]:
    kind = drivers.get("kind")
    if kind == "vice_streak":
        vs = rec.get("vice_streaks")
        if isinstance(vs, dict):
            vals = [float(v) for v in vs.values() if isinstance(v, (int, float))]
            return max(vals) if vals else None
        return None
    if kind == "all_pillars":
        vals = [s for p in PILLAR_NAMES if (s := _raw_score(rec, p)) is not None]
        return min(vals) if len(vals) >= 2 else None
    pillars = drivers.get("pillars") or []
    vals = [s for p in pillars if (s := _raw_score(rec, p)) is not None]
    if len(vals) != len(pillars) or not vals:
        return None  # a conjunction needs every driver measured that day
    return min(vals)


def _target_value(rec: dict, target: str) -> Optional[float]:
    if target == "_all":
        vals = [s for p in PILLAR_NAMES if (s := _raw_score(rec, p)) is not None]
        return sum(vals) / len(vals) if len(vals) >= 2 else None
    return _raw_score(rec, target)


def _lagged_pairs(records: list[dict], drivers: dict, target: str, lag_days: int) -> tuple[list[float], list[float]]:
    """Consecutive-day (driver t, target t+lag) pairs — a gap breaks the pair."""
    by_date = {}
    for rec in records:
        d = rec.get("date") or str(rec.get("sk", "")).replace("DATE#", "")
        if d:
            by_date[d] = rec
    xs, ys = [], []
    from datetime import timedelta

    for d, rec in sorted(by_date.items()):
        drv = _driver_value(rec, drivers)
        if drv is None:
            continue
        try:
            nxt = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        except ValueError:
            continue
        nrec = by_date.get(nxt)
        if not nrec:
            continue
        tgt = _target_value(nrec, target)
        if tgt is None:
            continue
        xs.append(drv)
        ys.append(tgt)
    return xs, ys


# ══════════════════════════════════════════════════════════════════════════════
# THE FIT
# ══════════════════════════════════════════════════════════════════════════════
def fit_effects(records: list[dict], config: dict[str, Any], as_of_date: Optional[str] = None) -> dict[str, Any]:
    """Fit every configured effect against the daily history. Pure + deterministic."""
    as_of = as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    specs = derive_fit_specs(config)

    rows = []
    for spec in specs:
        xs, ys = _lagged_pairs(records, spec["drivers"], spec["target"], spec["lag_days"])
        n = len(xs)
        r = pearson_r(xs, ys)
        n_eff = effective_sample_size(xs, ys) if n >= 3 else float(n)
        ci = moving_block_bootstrap_ci(xs, ys) if n >= 5 else None
        p = pearson_p_value(r, n_eff)
        rows.append(
            {
                "effect": spec["effect"],
                "target": spec["target"],
                "driver_kind": spec["drivers"]["kind"],
                "driver_pillars": spec["drivers"]["pillars"],
                "lag_days": spec["lag_days"],
                "expected_sign": spec["expected_sign"],
                "n": n,
                "n_eff": round(n_eff, 1),
                "r": round(r, 3) if r is not None else None,
                "ci_95": [round(ci[0], 3), round(ci[1], 3)] if ci else None,
                "p": p,
            }
        )

    # BH-FDR across the whole family — one correction over every pair tested.
    for row, q in zip(rows, bh_fdr([row["p"] for row in rows])):
        row["p_adj"] = round(q, 4) if q is not None else None

    for row in rows:
        row["status"], row["reason"] = _verdict(row)

    # Effect-level rollup: an effect is fitted only when EVERY target pair is.
    effects: dict[str, dict] = {}
    for row in rows:
        eff = effects.setdefault(
            row["effect"],
            {"status": STATUS_FITTED, "reason": "confirmed", "n_eff": None, "ci_95": None, "r": None, "targets": []},
        )
        eff["targets"].append(row)
        if row["status"] != STATUS_FITTED and eff["status"] == STATUS_FITTED:
            eff["status"] = STATUS_AUTHORED
            eff["reason"] = row["reason"]
    for eff in effects.values():
        # The rollup n_eff/CI is the weakest pair's — the honest bottleneck.
        weakest = min(eff["targets"], key=lambda t: t["n_eff"])
        eff["n_eff"] = weakest["n_eff"]
        eff["ci_95"] = weakest["ci_95"]
        eff["r"] = weakest["r"]

    n_days = len({rec.get("date") or str(rec.get("sk", "")).replace("DATE#", "") for rec in records})
    return {
        "as_of_date": as_of,
        "window_days": FIT_WINDOW_DAYS,
        "n_days": n_days,
        "alpha": ALPHA,
        "min_n_eff": MIN_N_EFF,
        "lag_days": LAG_DAYS,
        "method": "lagged pearson r · moving-block bootstrap 95% CI · BH-FDR · AR(1) n_eff (stats_core)",
        "effects": effects,
        "summary": {
            "tested": len(effects),
            "fitted": sum(1 for e in effects.values() if e["status"] == STATUS_FITTED),
            "authored_prior": sum(1 for e in effects.values() if e["status"] != STATUS_FITTED),
        },
    }


def _verdict(row: dict) -> tuple[str, str]:
    if row["r"] is None or row["ci_95"] is None or row["n_eff"] < MIN_N_EFF:
        return STATUS_AUTHORED, "insufficient_n"
    lo, hi = row["ci_95"]
    if hi < 0.0:
        # The CI confidently excludes the null on the WRONG side — the authored
        # direction is refuted, which is a stronger finding than an ambiguous null.
        return STATUS_AUTHORED, "sign_mismatch"
    if lo <= 0.0 or row["p_adj"] is None or row["p_adj"] > ALPHA:
        return STATUS_AUTHORED, "null_not_excluded"
    if row["r"] <= 0:
        return STATUS_AUTHORED, "sign_mismatch"
    return STATUS_FITTED, "confirmed"


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE + MERGE
# ══════════════════════════════════════════════════════════════════════════════
def build_fit_item(fit_result: dict[str, Any], user_id: str) -> dict[str, Any]:
    """DDB item for one fit run — floats become Decimal (boto3 contract)."""
    item = {
        "pk": effect_fits_pk(user_id),
        "sk": f"{FIT_SK_PREFIX}{fit_result['as_of_date']}",
        "fitted_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update(floats_to_decimal({k: v for k, v in fit_result.items()}, precision=4))
    return item


def _plain(obj: Any) -> Any:
    """Decimal → float/int for in-process consumers of a stored item."""
    if isinstance(obj, Decimal):
        f = float(obj)
        return int(f) if f.is_integer() else f
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def load_latest_fit(table: Any, user_id: str) -> Optional[dict[str, Any]]:
    """Latest FIT# item as plain python, or None. Never raises — an absent or
    unreadable fit degrades to the honest authored-prior default."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(effect_fits_pk(user_id)) & Key("sk").begins_with(FIT_SK_PREFIX),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return _plain(items[0]) if items else None
    except Exception as e:  # noqa: BLE001 — serving/compute paths must not die on the badge
        logger.warning("effect_fitter: load_latest_fit failed: %s", e)
        return None


def refit_due(latest_fit_item: Optional[dict], today: Optional[str] = None) -> bool:
    """Quarterly cadence, checked by the weekly hypothesis cron."""
    if not latest_fit_item:
        return True
    sk = str(latest_fit_item.get("sk", ""))
    date_part = sk[len(FIT_SK_PREFIX) :] if sk.startswith(FIT_SK_PREFIX) else ""
    try:
        last = datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        return True
    now = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now(timezone.utc).replace(tzinfo=None)
    if hasattr(now, "date") and not isinstance(now, datetime):  # pragma: no cover — defensive
        now = datetime.combine(now, datetime.min.time())
    return (now - last).days >= REFIT_INTERVAL_DAYS


def badge_text(effect: dict[str, Any]) -> str:
    """The one badge grammar (#1411): honest n + uncertainty on every claim."""
    if effect.get("fit_status") == STATUS_FITTED:
        n_eff = effect.get("fit_n_eff")
        ci = effect.get("fit_ci_95")
        parts = [f"n_eff={n_eff:.0f}" if isinstance(n_eff, (int, float)) else "n_eff=?"]
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            parts.append(f"95% CI [{ci[0]:.2f}, {ci[1]:.2f}]")
        return "fitted — " + ", ".join(parts)
    n_eff = effect.get("fit_n_eff")
    n_txt = f"{n_eff:.0f}" if isinstance(n_eff, (int, float)) else "0"
    return f"authored prior — not yet confirmed (n_eff={n_txt})"


def merge_fit_into_config(config: dict[str, Any], latest_fit: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Annotate config effects with the latest fit (in place; returns config).

    Without a fit every effect wears its declared authored-prior default — the
    config can never hand itself "fitted" (the test pins that), so the merged
    status is data-earned or honestly absent.
    """
    fit_effects_map = (latest_fit or {}).get("effects") or {}
    fitted_at = (latest_fit or {}).get("as_of_date")
    for effect in config.get("cross_pillar_effects", []) or []:
        effect.setdefault("fit_status", STATUS_AUTHORED)
        rec = fit_effects_map.get(effect.get("name"))
        if rec:
            effect["fit_status"] = rec.get("status", STATUS_AUTHORED)
            effect["fit_reason"] = rec.get("reason")
            effect["fit_n_eff"] = rec.get("n_eff")
            effect["fit_ci_95"] = rec.get("ci_95")
            effect["fit_r"] = rec.get("r")
            effect["fitted_at"] = fitted_at
        effect["fit_badge"] = badge_text(effect)
    return config
