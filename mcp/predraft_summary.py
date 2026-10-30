"""#5199: the nightly pre-draft's compact summary log line.

The full result line is clipped at 4000 chars and stops inside ``block_model``, so the keys an operator
needs (routine, critics, coach context, shadow, the legs) never reached CloudWatch. This builds ONE small
line, logged FIRST, where every key is always present: a missing leg reads ``{"state": "absent"}``, never a
missing key. Pure: no I/O, never raises (a failure to summarise is named in the line, not raised)."""

from __future__ import annotations

import json
from typing import Any

SUMMARY_MARK = "NIGHTLY_PREDRAFT_SUMMARY"
MAX_CHARS = 1800  # well under CloudWatch's 256 KB event limit; small enough to read at a glance
_VALUE = 80  # a single scalar is clipped here
ABSENT: dict[str, Any] = {"state": "absent"}


def _scalar(v: Any) -> Any:
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):  # #5247: a list stays a JSON list (its members clipped), never its Python repr
        return [_scalar(i) for i in v]
    s = str(v)
    return s if len(s) <= _VALUE else s[: _VALUE - 1] + "…"


def _pick(src: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(src, dict) or not src:
        return dict(ABSENT)
    return {k: _scalar(src.get(k)) for k in keys}


def _tracker(src: Any) -> dict[str, Any]:
    """#5247: ``write_latest`` returns the week's tracker status as ``status``; ``state`` stays as the fallback."""
    out = _pick(src, ("outcome", "sk"))
    if out != ABSENT:
        out["state"] = _scalar(src.get("status") if src.get("status") is not None else src.get("state"))
    return out


def _critics(c: Any) -> dict[str, Any]:
    if not isinstance(c, dict) or not c:
        return dict(ABSENT)
    verdicts = [v for v in c.get("verdicts") or [] if isinstance(v, dict)]
    counts: dict[str, int] = {}
    for v in verdicts:
        k = str(v.get("verdict"))
        counts[k] = counts.get(k, 0) + 1
    return {"model_ran": c.get("model_ran"), "veto": _scalar(c.get("veto")), "n": len(verdicts), "verdicts": counts}


def _coach_context(c: Any) -> dict[str, Any]:
    if not isinstance(c, dict) or not c:
        return dict(ABSENT)
    if c.get("state") == "read_failed":
        return {"state": "read_failed"}
    return {
        "stamp": c.get("context_version"),  # #5247: CONTEXT_VERSION already reads "coach-context@x.y.z"; never re-prefix it
        "charter_version": c.get("charter_version"),
        "not_supplied": _scalar(c.get("not_supplied")),
    }


def _shadow(s: Any) -> dict[str, Any]:
    if not isinstance(s, dict) or not s:
        return dict(ABSENT)
    return {"status": _scalar(s.get("outcome")), "key": _scalar(s.get("sk"))}


def _note_lint(n: Any) -> dict[str, Any]:
    """#5428: the drafted body's note lint — `clean` / `problems` (with the count and the rule ids) / `off` / `not_run`."""
    if not isinstance(n, dict) or not n:
        return dict(ABSENT)
    out = {"state": _scalar(n.get("state"))}
    if n.get("state") == "problems":
        out.update(problems=_scalar(n.get("problems")), rules=_scalar(n.get("rules")))
    return out


def summarise(result: dict[str, Any], charter_version: Any = None) -> dict[str, Any]:
    r = result if isinstance(result, dict) else {}
    out = {
        "job": _scalar(r.get("job")),
        "outcome": _scalar(r.get("outcome")),
        "target": _scalar(r.get("target_date")),
        "routine_id": _scalar(r.get("routine_id")),
        "routine_version": _scalar(r.get("routine_version")),
        "critics": _critics(r.get("critics")),
        "note_lint": _note_lint(r.get("note_lint")),
        "coach_context": _coach_context(r.get("coach_context")),
        "shadow": _shadow(r.get("shadow")),
        "may_tracker": _tracker(r.get("may_tracker")),
        "calibration": _pick(r.get("calibration"), ("outcome", "deadman")),
        "titration": _pick(r.get("titration"), ("outcome", "week", "action", "step_kcal", "reason_code")),
        "fitness_battery": _pick(r.get("fitness_battery"), ("outcome", "state")),
        "charter_version": _scalar(charter_version),
    }
    if r.get("error"):
        out["error"] = _scalar(r.get("error"))
    return out


def summary_line(result: dict[str, Any], charter_version: Any = None) -> str:
    try:
        body = json.dumps(summarise(result, charter_version), default=str, separators=(",", ":"))
    except Exception as e:  # noqa: BLE001 — a summary must never break the run
        body = json.dumps({"summary_error": type(e).__name__})
    return f"{SUMMARY_MARK} {body[:MAX_CHARS]}"
