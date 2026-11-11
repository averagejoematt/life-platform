"""tripwire_readers.py — the report-only readers for owner tripwires nothing else read (#5802).

WHY THIS EXISTS

On 2026-11-11 `owner_redlines.unevaluated_tripwires()` returned 19 of the 28 tripwires, and 16
of them had no reader anywhere: the owner and every coach were shown a posture that could never
fire. #5802 gave each one a disposition — wire, merge or propose-delete. This module is the
WIRE half for the tripwires whose inputs the nutrition-critics resolver
(`mcp.nutrition_critics_inputs`) already reads, or reads beside them:

  loss_acceptable                the 14-day trend inside ± `tolerance_pct` of the served target
  loss_insufficient_adherent     both weekly checkpoints (21 days) under the % of target, logging and protein on plan
  loss_insufficient_nonadherent  the 14-day trend under the % of target, logging or walking under the floor
  under_floor                    logged days under `threshold_kcal` in the trailing 7
  walking_vs_fork                both weeks under the walking floor while the trend is at or above target
  weigh_in_dark                  days since the last weigh-in, as of the window's last day
  lean_mass                      the lean share of the loss (and lean lb/wk) across the last DXA interval
  sleep                          the trailing 7-day mean sleep under the line on each of the last N days

REPORT-ONLY, ALWAYS. Every row carries `report_only: True`; nothing here vetoes, changes a
draft or a calorie number. Making any of them act is a separate owner ruling that names the
check it retires (#5802 acceptance).

THE THREE STATES. `tripped` (the signal's condition holds), `clear` (it does not), `unknown` (an
input could not be read, or was too thin to read) — an unknown input is NEVER a pass (ADR-104).
For `loss_acceptable` `tripped` means "on schedule": the base case the other rate rules are
exceptions to, so it is a computed state rather than the absence of a flag.

Thresholds are read BY ID from `training.owner_redlines` at call time — never a literal here.
`stall_from_block` is the other half of #5802: plan_engine's `weight_stall_with_adherence` row
reads nutrition_critics' ONE evaluation through it instead of an input path of its own.

PURE: the inputs are the resolver's plain dict; no I/O.
"""

from __future__ import annotations

from typing import Any

from common.pacific_time import parse_day_key
from training import owner_redlines
from training.redline_rate import _dxa_point

from health import nutrition_critics as nc, protein_engine

READER_IDS = (
    "loss_acceptable",
    "loss_insufficient_adherent",
    "loss_insufficient_nonadherent",
    "under_floor",
    "walking_vs_fork",
    "weigh_in_dark",
    "lean_mass",
    "sleep",
    "medical_stop_lines",
    "mood_declared",
    "joy",
)
# the share of a 7-day window that must be measured before its mean is read (a mean over two nights is not a week)
SLEEP_MIN_NIGHTS_OF_7 = 4
LOGGING_ON_PLAN_DAYS_OF_7 = 6  # the rate rules' own "logging ≥ 6/7" (owner_redlines `loss_insufficient_*` signal text)


def _row(tid: str, state: str, observed: Any, detail: str, unknown: list[str] | None = None) -> dict[str, Any]:
    t = nc._tripwire(tid)
    row = {
        "id": tid,
        "state": state,
        "observed": observed,
        "detail": detail,
        "signal": t["signal"],
        "action_if_tripped": t["action"],
        "provenance": t["provenance"],
        "report_only": True,
        "evaluated_by": "health.tripwire_readers",
    }
    if unknown:
        row["unknown"] = unknown
    return row


def _unknown(tid: str, missing: list[str], why: str) -> dict[str, Any]:
    return _row(tid, "unknown", None, f"{why} — not read, not clear", missing)


def _target(inputs: dict[str, Any]) -> float | None:
    """The SERVED rate target (protein-gated, body-fat tiered, guidance-capped) — the deficit advocate's own number."""
    missed, measured = nc._protein7_counts(inputs)
    t = nc._served_target(nc._num(inputs.get("weight_lb")), missed, measured, inputs)
    return None if t is None else nc._num(t.get("target_lb_wk"))


def _rate_inputs(inputs: dict[str, Any]) -> tuple[float | None, float | None, list[str]]:
    """(the 14-day loss rate lb/wk, the served target, the missing names) — a provisional rate is unreadable."""
    loss, target = nc._loss_rate(inputs), _target(inputs)
    missing = [k for k, v in (("weight_trend_lb_wk", loss), ("rate_target", target)) if v is None]
    if inputs.get("rate_provisional"):
        missing.append("rate_provisional")
    return loss, target, missing


def _logged_days_7(inputs: dict[str, Any]) -> int | None:
    s = nc._series(inputs, "intake_kcal_by_day")
    return None if s is None else len(nc._logged(s[-7:]))


def _protein_on_plan(inputs: dict[str, Any]) -> bool | None:
    s = nc._series(inputs, "protein_g_by_day")
    if s is None:
        return None
    return sum(1 for g in nc._logged(s[-7:]) if protein_engine.hit(g)) >= owner_redlines.REDLINES["protein_floor_g"]["days_of_7"]


def _walking_floor() -> float:
    return float(owner_redlines.REDLINES["walking_floor_hr_wk"]["value"])


def loss_acceptable(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("loss_acceptable")
    loss, target, missing = _rate_inputs(inputs)
    if missing:
        return _unknown(t["id"], missing, "the 14-day trend or the served target could not be read")
    tol = target * float(t["tolerance_pct"]) / 100
    inside = abs(loss - target) <= tol
    detail = f"14-day trend {loss} lb/wk vs served target {target} (± {t['tolerance_pct']} %)"
    return _row(t["id"], "tripped" if inside else "clear", loss, detail + (" — on schedule" if inside else " — outside the band"))


def loss_insufficient_adherent(inputs: dict[str, Any]) -> dict[str, Any]:
    """21 days = the two counted weekly checkpoints (each a 14-day trend, ending `end` and `end − 7`), both under the line."""
    t = nc._tripwire("loss_insufficient_adherent")
    _, target, missing = _rate_inputs(inputs)
    weekly = [r for r in (nc._num(x) for x in (inputs.get("weekly_loss_rates_lb_wk") or [])) if r is not None]
    logged, protein_ok = _logged_days_7(inputs), _protein_on_plan(inputs)
    missing = [m for m in missing if m != "weight_trend_lb_wk"]
    missing += [
        k for k, v in (("weekly_loss_rates_lb_wk", weekly[-2:] if len(weekly) >= 2 else None), ("intake_kcal_by_day", logged)) if v is None
    ]
    missing += ["protein_g_by_day"] if protein_ok is None else []
    if missing:
        return _unknown(t["id"], missing, "two counted weekly checkpoints, the logging count and the protein count are all needed")
    line = target * float(t["threshold_pct_of_target"]) / 100
    slow = all(r < line for r in weekly[-2:])
    adherent = logged >= LOGGING_ON_PLAN_DAYS_OF_7 and protein_ok
    detail = f"weekly checkpoints {weekly[-2:]} lb/wk vs {line:.2f} ({t['threshold_pct_of_target']} % of target); logged {logged}/7, protein floor met={protein_ok}"
    return _row(t["id"], "tripped" if slow and adherent else "clear", weekly[-2:], detail)


def loss_insufficient_nonadherent(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("loss_insufficient_nonadherent")
    loss, target, missing = _rate_inputs(inputs)
    if missing:
        return _unknown(t["id"], missing, "the 14-day trend or the served target could not be read")
    line = target * float(t["threshold_pct_of_target"]) / 100
    logged, walk = _logged_days_7(inputs), nc._num(inputs.get("walking_hr_this_wk"))
    arms = [None if logged is None else logged < LOGGING_ON_PLAN_DAYS_OF_7, None if walk is None else walk < _walking_floor()]
    detail = f"14-day trend {loss} lb/wk vs {line:.2f} ({t['threshold_pct_of_target']} % of target); logged {logged}/7, walking {walk} h vs floor {_walking_floor()}"
    if loss >= line:
        return _row(t["id"], "clear", loss, detail)
    if any(a is True for a in arms):
        return _row(t["id"], "tripped", loss, detail)
    if any(a is None for a in arms):
        names = [k for k, a in (("intake_kcal_by_day", arms[0]), ("walking_hr_this_wk", arms[1])) if a is None]
        return _unknown(t["id"], names, f"{detail}; the adherence half could not be read")
    return _row(t["id"], "clear", loss, detail + " — adherent, so `loss_insufficient_adherent` is the arm")


def under_floor(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("under_floor")
    s = nc._series(inputs, "intake_kcal_by_day")
    if s is None:
        return _unknown(t["id"], ["intake_kcal_by_day"], "the MacroFactor partition could not be read")
    below = [v for v in nc._logged(s[-7:]) if v < float(t["threshold_kcal"])]
    detail = f"{len(below)} logged day(s) of the trailing 7 under the line (threshold {t['threshold_days']}); an unlogged day is `logging_dark`'s, not counted here"
    return _row(t["id"], "tripped" if len(below) >= int(t["threshold_days"]) else "clear", len(below), detail)


def walking_vs_fork(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("walking_vs_fork")
    loss, target, missing = _rate_inputs(inputs)
    this_wk, last_wk = nc._num(inputs.get("walking_hr_this_wk")), nc._num(inputs.get("walking_hr_last_wk"))
    missing += [k for k, v in (("walking_hr_this_wk", this_wk), ("walking_hr_last_wk", last_wk)) if v is None]
    if missing:
        return _unknown(t["id"], missing, "both weeks' walking hours and the trend vs target are needed")
    under = this_wk < _walking_floor() and last_wk < _walking_floor()
    detail = f"walking {last_wk} h then {this_wk} h vs floor {_walking_floor()}; 14-day trend {loss} vs target {target} lb/wk"
    return _row(t["id"], "tripped" if under and loss >= target else "clear", [last_wk, this_wk], detail)


def weigh_in_dark(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("weigh_in_dark")
    end, last = inputs.get("window_end"), inputs.get("last_weighin_date")
    if not end or not parse_day_key(str(end)):
        return _unknown(t["id"], ["window_end"], "no window end to count from")
    if last and parse_day_key(str(last)):
        days = (parse_day_key(str(end)) - parse_day_key(str(last))).days
        detail = f"last weigh-in {last}, {days} day(s) before {end} (threshold {t['threshold_days']})"
        return _row(t["id"], "tripped" if days >= int(t["threshold_days"]) else "clear", days, detail)
    if inputs.get("weighin_count") == 0:  # the Withings read SUCCEEDED and held no weigh-in: dark, not unknown
        return _row(t["id"], "tripped", None, f"no weigh-in in the Withings window ending {end}")
    return _unknown(t["id"], ["last_weighin_date"], "the Withings partition could not be read")


def lean_mass(inputs: dict[str, Any]) -> dict[str, Any]:
    """Across the LAST DXA interval (the two most recent readable scans): lean share of the loss and lean lb/wk."""
    t = nc._tripwire("lean_mass")
    th = t["threshold"]
    scans = inputs.get("dxa_scans")
    if scans is None:
        return _unknown(t["id"], ["dxa_scans"], "the DXA partition could not be read")
    pts = [p for p in (_dxa_point(r) for r in scans) if p]
    if len(pts) < 2:
        return _unknown(t["id"], ["dxa_scans"], f"{len(pts)} readable DXA scan(s) — an interval needs two")
    a, b = pts[-2], pts[-1]
    weeks = (parse_day_key(b["scan_date"]) - parse_day_key(a["scan_date"])).days / 7
    lean_lost = a["lean_lb"] - b["lean_lb"]
    lean_wk = round(lean_lost / weeks, 2) if weeks > 0 else None
    total_lost = (a["scan_weight_lb"] - b["scan_weight_lb"]) if a["scan_weight_lb"] and b["scan_weight_lb"] else None
    share = round(lean_lost / total_lost * 100, 1) if total_lost and total_lost > 0 else None
    app = _appendicular_vs_week0(scans)
    observed = {"interval": [a["scan_date"], b["scan_date"]], "lean_share_pct": share, "lean_lb_wk": lean_wk, **app}
    pct, app_line = app["appendicular_lean_pct_vs_week0"], th["maintenance_at_appendicular_lean_pct"]
    arms = [
        None if share is None else share > th["lean_share_pct"],
        None if lean_wk is None else lean_wk > th["lean_lb_wk"],
        None if pct is None else pct <= app_line,
    ]
    escalate = (share is not None and share > th["maintenance_at_lean_share_pct"]) or arms[2] is True
    observed["escalation"] = "maintenance_until_next_scan" if escalate else None
    detail = (
        f"DXA {a['scan_date']} → {b['scan_date']}: lean share of the loss {share} %, lean {lean_wk} lb/wk; "
        f"appendicular lean {pct} % vs the week-0 scan {app['week0_scan']}"
    )
    if any(x is True for x in arms):
        return _row(t["id"], "tripped", observed, detail)
    if any(x is None for x in arms):
        return _row(
            t["id"], "unknown", observed, detail + " — an arm unreadable (no loss across the interval, a scan weight or limb missing)"
        )
    return _row(t["id"], "clear", observed, detail)


_LIMBS = ("right_arm", "left_arm", "right_leg", "left_leg")


def _appendicular_lb(row: dict[str, Any]) -> float | None:
    """Arms + legs lean (lb) of one DXA row (`limbs.<limb>.lean_lb`), or None when any limb is missing — never a partial sum."""
    limbs = (row or {}).get("limbs") or {}
    vals = [nc._num((limbs.get(k) or {}).get("lean_lb")) for k in _LIMBS]
    return None if any(v is None for v in vals) else sum(vals)


def _appendicular_vs_week0(scans: list[dict[str, Any]]) -> dict[str, Any]:
    """The latest scan's appendicular lean vs the week-0 scan (`medical_cover.week0_reference.dxa.date`), in %."""
    w0_date = owner_redlines.REDLINES["medical_cover"]["week0_reference"]["dxa"]["date"]
    w0 = next((r for r in scans if str(r.get("scan_date") or "") == w0_date), None)
    latest = scans[-1] if scans else None
    base, now = (_appendicular_lb(w0) if w0 else None), (_appendicular_lb(latest) if latest else None)
    pct = round((now - base) / base * 100, 1) if base and now is not None and latest is not w0 else None
    return {"week0_scan": w0_date if w0 else None, "appendicular_lean_pct_vs_week0": pct}


def _sleep_means(s: list[Any], days: int) -> list[float | None]:
    """The trailing 7-day mean ending on each of the last `days` days; None where under SLEEP_MIN_NIGHTS_OF_7 are measured."""
    out: list[float | None] = []
    for end in range(len(s) - days, len(s)):
        win = nc._logged(s[max(0, end - 6) : end + 1])
        out.append(round(sum(win) / len(win), 2) if len(win) >= SLEEP_MIN_NIGHTS_OF_7 else None)
    return out


def sleep(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("sleep")
    s = nc._series(inputs, "sleep_hours_by_day")
    if s is None:
        return _unknown(t["id"], ["sleep_hours_by_day"], "the Whoop partition could not be read")
    means = _sleep_means(s, int(t["consecutive_days"]))
    line = float(t["threshold_hours"])
    detail = f"trailing 7-day mean sleep on each of the last {t['consecutive_days']} days: {means} vs {line} h (Whoop sleep_duration_hours)"
    if any(m is not None and m >= line for m in means):
        return _row(t["id"], "clear", means, detail)
    if any(m is None for m in means):
        return _row(t["id"], "unknown", means, detail + f" — a day with under {SLEEP_MIN_NIGHTS_OF_7} measured nights of 7")
    return _row(t["id"], "tripped", means, detail)


# ── medical_stop_lines: which lines are MEASURED, which stay self-report ─────────────────────
# `medical_cover.stop_lines`, each mapped to the measured input that can read it — or to None (self-report or not on any
# panel). A stop line with no measured input is `unknown`, every time: the row can trip on a measured line, and it can
# NEVER read clear while a self-report line is unread (#5802, owner veto 2026-11-11).
LAB_FRESH_DAYS = 56  # `medical_cover.labs_cadence`: every 8 weeks with the DXA — an older draw is not a current read
# stop line (verbatim from `medical_cover.stop_lines`) -> the labs marker keys that read it; the threshold is parsed from
# the line's own text (`_nums`), never re-typed here
_LAB_LINES = {"K < 3.5": ("potassium",), "Na < 133": ("sodium",), "uric acid > 9 or a flare": ("uric_acid",)}
_MG_PO4, _ALT, _EGFR, _RHR = (
    "Mg < 1.7 or PO4 < 2.5",
    "ALT > 3× ULN",
    "eGFR worse than −25 % from baseline",
    "RHR +12 over the 14-day baseline",
)
_SELF_REPORT_LINES = {
    "QTc > 470": "a 12-lead ECG reading; the clinical ECG rows are consumer single-lead recordings with no QTc",
    "orthostatic SBP drop > 20 or syncope": "orthostatic BP and syncope are not measured by any device on the platform",
    "PHQ-9 ≥ 10 or any item 9 (stop AND firewall)": "the PHQ-9 is the check-in lane's input (#5819)",
    "a gout flare (the uric-acid line's second half)": "self-report",
    "RUQ pain": "self-report (the tripwire's signal)",
    "palpitations": "self-report (the tripwire's signal; an ECG recording is evidence of a rhythm, not of the symptom)",
}
MEASURED_LINES = (*_LAB_LINES, _MG_PO4, _ALT, _EGFR, _RHR)


def _nums(line: str) -> list[float]:
    import re

    # only a number that follows a comparison or a sign — "PO4" and "eGFR" carry digits that are not thresholds
    return [float(x) for x in re.findall(r"[<>≥≤−+-]\s*(\d+(?:\.\d+)?)", line)]


def _lab_value(draw: dict[str, Any] | None, keys: tuple[str, ...]) -> float | None:
    bms = (draw or {}).get("biomarkers") or {}
    for k in keys:
        cell = bms.get(k)
        if isinstance(cell, dict):
            v = nc._num(cell.get("value_numeric", cell.get("value")))
            if v is not None:
                return v
    return None


def _lab_uln(draw: dict[str, Any] | None, key: str) -> float | None:
    """The upper limit of normal from the marker's own `ref_text` ('10-44', '<44', '0 - 44 IU/L'), or None."""
    import re

    text = str((((draw or {}).get("biomarkers") or {}).get(key) or {}).get("ref_text") or "")
    m = re.search(r"(?:-|–|<|≤)\s*(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _draw_date(draw: dict[str, Any] | None) -> str | None:
    d = str((draw or {}).get("draw_date") or str((draw or {}).get("sk") or "").replace("DATE#", ""))[:10]
    return d if parse_day_key(d) else None


def _arm(value: float | None, tripped: bool | None, as_of: str | None, fresh: bool, why_none: str) -> dict[str, Any]:
    """One stop line's read. A clear on a stale draw is NOT a clear (unknown); a crossed line on any draw is tripped."""
    if tripped is True:
        return {"state": "tripped", "as_of": as_of}
    if value is None or tripped is None:
        return {"state": "unknown", "as_of": as_of, "why": why_none}
    if not fresh:
        return {"state": "unknown", "as_of": as_of, "why": f"the draw is older than {LAB_FRESH_DAYS} days"}
    return {"state": "clear", "as_of": as_of}


def _medical_lab_arms(draws: list[dict[str, Any]], end: str | None) -> dict[str, dict[str, Any]]:
    """One {state, as_of, why?} per lab stop line over the latest draw (fresh within LAB_FRESH_DAYS of `end`)."""
    latest = draws[-1] if draws else None
    as_of = _draw_date(latest)
    end_d, as_of_d = parse_day_key(str(end)) if end else None, parse_day_key(as_of) if as_of else None
    fresh = bool(end_d and as_of_d and (end_d - as_of_d).days <= LAB_FRESH_DAYS)
    arms: dict[str, dict[str, Any]] = {}
    for line, keys in _LAB_LINES.items():
        v, th = _lab_value(latest, keys), _nums(line)[0]
        arms[line] = _arm(v, None if v is None else (v < th if "<" in line else v > th), as_of, fresh, "not on the latest panel")
    mg_th, po4_th = _nums(_MG_PO4)
    mg, po4 = _lab_value(latest, ("magnesium", "magnesium_serum")), _lab_value(latest, ("phosphorus", "phosphate"))
    low = (mg is not None and mg < mg_th) or (po4 is not None and po4 < po4_th)
    known = mg is not None and po4 is not None
    arms[_MG_PO4] = _arm(
        mg if known else None, True if low else (False if known else None), as_of, fresh, "serum Mg / PO4 not on the panel"
    )
    alt, uln = _lab_value(latest, ("alt",)), _lab_uln(latest, "alt")
    alt_trip = None if (alt is None or uln is None) else alt > _nums(_ALT)[0] * uln
    arms[_ALT] = _arm(alt if uln else None, alt_trip, as_of, fresh, "ALT or its reference range not on the panel")
    w0 = owner_redlines.REDLINES["medical_cover"]["week0_reference"]["labs"]["date"]
    base = _lab_value(next((d for d in draws if _draw_date(d) == w0), None), ("egfr",))
    now = _lab_value(latest, ("egfr",)) if as_of != w0 else None
    drop = None if (base is None or now is None) else (now - base) / base * 100
    egfr_trip = None if drop is None else drop < -_nums(_EGFR)[0]
    arms[_EGFR] = _arm(drop, egfr_trip, as_of, fresh, "no eGFR on the baseline draw and a later one")
    return arms


def _rhr_arm(rhr: list[Any] | None) -> dict[str, Any]:
    """RHR +N over the 14-day baseline: the latest night vs the mean of the nights before it (Whoop)."""
    vals = [nc._num(v) for v in (rhr or [])]
    prior, last = [v for v in vals[:-1] if v is not None], (vals[-1] if vals else None)
    if last is None or len(prior) < 7:
        return {"state": "unknown", "why": "no latest night, or under 7 baseline nights"}
    rise = last - sum(prior) / len(prior)
    return {"state": "tripped" if rise >= _nums(_RHR)[0] else "clear", "rise_bpm": round(rise, 1)}


def medical_stop_lines(inputs: dict[str, Any]) -> dict[str, Any]:
    t = nc._tripwire("medical_stop_lines")
    draws = inputs.get("lab_draws")
    unread = {"state": "unknown", "why": "the labs partition could not be read"}
    lab_arms = _medical_lab_arms(draws, inputs.get("window_end")) if draws is not None else {k: dict(unread) for k in MEASURED_LINES[:-1]}
    arms = {**lab_arms, _RHR: _rhr_arm(inputs.get("rhr_by_day"))}
    arms.update({line: {"state": "unknown", "why": why} for line, why in _SELF_REPORT_LINES.items()})
    tripped = [line for line, a in arms.items() if a["state"] == "tripped"]
    observed = {"arms": arms, "measured": list(MEASURED_LINES), "self_report_only": list(_SELF_REPORT_LINES)}
    if tripped:
        return _row(t["id"], "tripped", observed, f"stop line(s) crossed: {', '.join(tripped)}")
    unread_lines = [line for line, a in arms.items() if a["state"] == "unknown"]
    return _row(
        t["id"],
        "unknown",
        observed,
        f"no measured stop line crossed; {len(unread_lines)} line(s) unread (self-report or no current panel) — never clear",
    )


# ── mood_declared and joy: SHELLS — the input is the check-in lane's (#5819); this lane never reads it ─────────
_CHECKIN_LANE = "input owned by the check-in lane (#5819) — not supplied"


def mood_declared(inputs: dict[str, Any]) -> dict[str, Any]:
    """Pure over an injected `mood_instrument` {phq9_total, phq9_item9, grief_event, declared, as_of}; absent ⇒ unknown."""
    t = nc._tripwire("mood_declared")
    m = inputs.get("mood_instrument")
    if not isinstance(m, dict):
        return _unknown(t["id"], ["mood_instrument"], _CHECKIN_LANE)
    total, item9 = nc._num(m.get("phq9_total")), nc._num(m.get("phq9_item9"))
    arms = {
        "phq9_total": None if total is None else total >= float(t["phq9_at_least"]),
        "phq9_item9": None if item9 is None else item9 > 0,
        "grief_event": m.get("grief_event") if isinstance(m.get("grief_event"), bool) else None,
        "declared": m.get("declared") if isinstance(m.get("declared"), bool) else None,
    }
    detail = f"the instrument of {m.get('as_of') or 'an unstated date'}: " + ", ".join(f"{k}={v}" for k, v in arms.items())
    if any(v is True for v in arms.values()):
        return _row(t["id"], "tripped", sorted(k for k, v in arms.items() if v), detail)
    if any(v is None for v in arms.values()):
        return _row(t["id"], "unknown", None, detail + " — an arm unread", [k for k, v in arms.items() if v is None])
    return _row(t["id"], "clear", [], detail)


def joy(inputs: dict[str, Any]) -> dict[str, Any]:
    """Pure over injected weekly `joy_answers` (True yes / False no / None unanswered, oldest first) and `weight_lb`."""
    t = nc._tripwire("joy")
    rule = t["threshold_rule"]
    answers = inputs.get("joy_answers")
    if not isinstance(answers, (list, tuple)):
        return _unknown(t["id"], ["joy_answers"], _CHECKIN_LANE)
    last = list(answers)[-int(rule["no_answers"]) :]
    weight = nc._num(inputs.get("weight_lb"))
    detail = f"the last {rule['no_answers']} weekly answers: {last}"
    if any(a is True for a in last):
        return _row(t["id"], "clear", last, detail)
    if len(last) < int(rule["no_answers"]) or any(a is not False for a in last):
        return _row(t["id"], "unknown", last, detail + " — a week unanswered", ["joy_answers"])
    if weight is None:
        return _row(t["id"], "unknown", last, detail + " — the weight the rule is armed above is unread", ["weight_lb"])
    armed = weight > float(rule["above_lb"])
    return _row(
        t["id"], "tripped" if armed else "clear", last, detail + ("" if armed else " — the rule is armed only above its weight line")
    )


_READERS = {
    "loss_acceptable": loss_acceptable,
    "loss_insufficient_adherent": loss_insufficient_adherent,
    "loss_insufficient_nonadherent": loss_insufficient_nonadherent,
    "under_floor": under_floor,
    "walking_vs_fork": walking_vs_fork,
    "weigh_in_dark": weigh_in_dark,
    "lean_mass": lean_mass,
    "sleep": sleep,
    "medical_stop_lines": medical_stop_lines,
    "mood_declared": mood_declared,
    "joy": joy,
}


def evaluate(inputs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One report-only row per wired tripwire, in READER_IDS order. A reader that raises reads `read_failed`, never clear."""
    inputs = inputs or {}
    out: list[dict[str, Any]] = []
    for tid in READER_IDS:
        try:
            out.append(_READERS[tid](inputs))
        except Exception as e:  # noqa: BLE001 — one broken reader is named, the rest still report
            out.append(_row(tid, "read_failed", None, f"the reader raised {type(e).__name__}: {e}"[:200]))
    return out


def stall_from_block(block: dict[str, Any] | None) -> dict[str, Any]:
    """`weight_stall_with_adherence` as `nutrition_critics.decisions_offered` evaluated it (#5802) — the ONE evaluation,
    read by plan_engine instead of an input path of its own. decisions_offered emits a record only when the trigger
    tripped (`pending` / `already_decided`) or could not be read (`unevaluable`); a built block with neither is `clear`."""
    tid = "weight_stall_with_adherence"
    if not isinstance(block, dict) or block.get("error") or not isinstance(block.get("decisions_offered"), list):
        err = block.get("error") if isinstance(block, dict) else None
        err = err or "no block"
        return {"state": "read_failed", "observed": None, "detail": f"the nutrition critics block was not built ({err})", "error": err}
    as_of = f"nutrition_critics, window ending {block.get('window_end') or 'unstated'}"
    rec = next((d for d in block["decisions_offered"] if isinstance(d, dict) and (d.get("trigger") or {}).get("id") == tid), None)
    if rec is None:
        return {"state": "clear", "observed": None, "detail": f"not tripped ({as_of})"}
    if rec.get("state") == "unevaluable":
        return {"state": "unknown", "observed": None, "detail": f"unevaluable: {', '.join(rec.get('unknown') or [])} ({as_of})"}
    values = (rec.get("trigger") or {}).get("values") or {"already_decided": rec.get("already_decided")}
    return {"state": "tripped", "observed": values, "detail": f"{rec.get('state')} — a diet-break / refeed decision is offered ({as_of})"}
