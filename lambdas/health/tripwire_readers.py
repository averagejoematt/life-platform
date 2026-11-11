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
    observed = {"interval": [a["scan_date"], b["scan_date"]], "lean_share_pct": share, "lean_lb_wk": lean_wk}
    arms = [None if share is None else share > th["lean_share_pct"], None if lean_wk is None else lean_wk > th["lean_lb_wk"]]
    detail = f"DXA {a['scan_date']} → {b['scan_date']}: lean share of the loss {share} %, lean {lean_wk} lb/wk; appendicular-lean arm not computed"
    if any(x is True for x in arms):
        return _row(t["id"], "tripped", observed, detail)
    if any(x is None for x in arms):
        return _row(t["id"], "unknown", observed, detail + " — one arm unreadable (no loss across the interval, or a scan weight missing)")
    return _row(t["id"], "clear", observed, detail)


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


_READERS = {
    "loss_acceptable": loss_acceptable,
    "loss_insufficient_adherent": loss_insufficient_adherent,
    "loss_insufficient_nonadherent": loss_insufficient_nonadherent,
    "under_floor": under_floor,
    "walking_vs_fork": walking_vs_fork,
    "weigh_in_dark": weigh_in_dark,
    "lean_mass": lean_mass,
    "sleep": sleep,
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
