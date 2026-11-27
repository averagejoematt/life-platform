"""development_profile_base.py — the vocabulary and small pure helpers the development profile is built from (#6294).

Split out of `health.development_profile` so the measured indicators (`health.development_profile_measured`) and the
assembly share one definition of a window, a direction and an indicator. Pure: no I/O, no clock.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional

from common.pacific_time import parse_day_key

# ── statuses, bases, directions ───────────────────────────────────────────────────────────────
IMPROVING, STEADY, HARDER, MIXED, NOT_ENOUGH = "improving", "steady", "harder", "mixed", "not_enough_to_say"
#: #6294 amendment (owner, 2026-11-26): an OPEN correction of his on a domain line — the profile then does not assert
#: its own status; the rule-derived value is kept beside it as `rule_status`.
OWNER_DISPUTED = "owner_disputed"
STATUSES: tuple[str, ...] = (IMPROVING, STEADY, HARDER, MIXED, NOT_ENOUGH, OWNER_DISPUTED)

MEASURED, COUNTED, OWN_REPORT, OWNER_CONFIRMED = "measured", "counted_from_records", "own_report", "owner_confirmed_records"
BASES: tuple[str, ...] = (MEASURED, COUNTED, OWN_REPORT, OWNER_CONFIRMED)

BETTER, SAME, WORSE, MIXED_DIR, INSUFFICIENT = "better", "same", "worse", "mixed", "insufficient"

#: What not_enough_to_say means — the owner's ruling (2026-11-26): "do not equate missing structured records with a
#: lack of real-world learning, emotional growth or self-understanding."
NOT_ENOUGH_MEANS = (
    "the platform holds too few structured records to form a view; this says nothing about what has actually " "happened in his life"
)

# ── the stated windows, minimums and margins ──────────────────────────────────────────────────
MEASURED_WINDOW_DAYS = 28
MEASURED_MIN_DAYS = 14
STATEMENT_CHARS = 240


def _day(value: Any) -> Optional[date]:
    s = str(value or "")[:10]
    return parse_day_key(s) if len(s) == 10 else None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _require_day(value: str) -> date:
    d = parse_day_key(value)
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {value!r}")
    return d


def windows(today: str, days: int) -> dict[str, tuple[str, str]]:
    """The recent window (ending on `today`, inclusive) and the equal window before it, as day keys."""
    t = _require_day(today)
    return {
        "recent": ((t - timedelta(days=days - 1)).isoformat(), t.isoformat()),
        "prior": ((t - timedelta(days=2 * days - 1)).isoformat(), (t - timedelta(days=days)).isoformat()),
    }


def _which(d: Optional[date], wins: Mapping[str, tuple[str, str]]) -> Optional[str]:
    if d is None:
        return None
    s = d.isoformat()
    for name, (lo, hi) in wins.items():
        if lo <= s <= hi:
            return name
    return None


def _days_in(lo: str, hi: str) -> list[str]:
    a, b = _require_day(lo), _require_day(hi)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _clip(text: Any) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= STATEMENT_CHARS else s[: STATEMENT_CHARS - 1] + "…"


def _indicator(key: str, label: str, direction: str, reason: str, evidence: dict[str, Any], *, counts: bool = True) -> dict[str, Any]:
    """One indicator. `counts=False` is CONTEXT: shown with its evidence, never part of the status computation."""
    return {"key": key, "label": label, "direction": direction, "reason": reason, "evidence": evidence, "counts": counts}


def _compare(recent: float, prior: float, margin: float, *, lower_is_better: bool = False) -> str:
    delta = recent - prior
    if abs(delta) < margin:
        return SAME
    up = delta > 0
    return BETTER if up != lower_is_better else WORSE


def combine(directions: Iterable[str]) -> str:
    """The domain status from its counting indicators' directions. Insufficient ones are ignored; none left -> not enough."""
    got = [d for d in directions if d != INSUFFICIENT]
    if not got:
        return NOT_ENOUGH
    if MIXED_DIR in got or (BETTER in got and WORSE in got):
        return MIXED
    if BETTER in got:
        return IMPROVING
    if WORSE in got:
        return HARDER
    return STEADY


def _excluded(inputs: Mapping[str, Any]) -> dict[str, set[str]]:
    ex = inputs.get("excluded_days") or {}
    return {k: {str(d)[:10] for d in (ex.get(k) or [])} for k in ("sick", "travel")}


def _eligible_days(
    inputs: Mapping[str, Any], wins: Mapping[str, tuple[str, str]], extra_observed: Iterable[str]
) -> dict[str, dict[str, Any]]:
    observed = {str(d)[:10] for d in (inputs.get("observed_days") or [])} | {str(d)[:10] for d in extra_observed}
    ex = _excluded(inputs)
    paused = ex["sick"] | ex["travel"]
    out = {}
    for name, (lo, hi) in wins.items():
        span = _days_in(lo, hi)
        obs = [d for d in span if d in observed]
        out[name] = {
            "days": [d for d in obs if d not in paused],
            "observed": len(obs),
            "excluded_sick": sum(1 for d in obs if d in ex["sick"]),
            "excluded_travel": sum(1 for d in obs if d in ex["travel"] and d not in ex["sick"]),
        }
    return out


def _read_failed(inputs: Mapping[str, Any], *names: str) -> list[str]:
    failed = inputs.get("read_failed") or {}
    return [n for n in names if n in failed]


def _failed_indicator(key: str, label: str, failed: list[str], *, counts: bool = True) -> dict[str, Any]:
    return _indicator(key, label, INSUFFICIENT, f"read failed: {', '.join(failed)} — not observed, never a zero", {}, counts=counts)


def _window_block(wins: Mapping[str, tuple[str, str]]) -> dict[str, dict[str, str]]:
    return {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()}


def _measured_evidence(today, wins, n, fig, unit, source, elig, label, *, counts: bool = True) -> dict[str, Any]:
    return {
        "date": today,
        "source": source,
        "evidence_kind": "measured",
        "statement": f"{label}: recent {fig['recent']} over {n['recent']} eligible days, prior {fig['prior']} over {n['prior']} eligible days",
        "window": _window_block(wins),
        "n": n,
        "excluded": {k: {"sick": elig[k]["excluded_sick"], "travel": elig[k]["excluded_travel"]} for k in wins},
        "figure": {**fig, "unit": unit},
        "counts_toward_status": counts,
    }
