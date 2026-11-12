"""public_brief_disputes.py — brief-native disagreements between coaches (Coaching Room CR3, owner approval 2026-11-12).

WHAT IT IS. The weekly brief runs its coaches in registry order (``coach.public_brief.brief_coaches``). A later coach is
shown the earlier coaches' current-cycle calls on the metrics it also reads (weight, resting heart rate, HRV and
calories are shared) — the RENDERED claim and its structure, never the earlier coach's own words — and may return
``disputes``: a call of its own on the same metric that says the opposite.

THE OPPOSITION RULE (``opposition``), decided by code, never by the model:
  * two direction calls oppose when they name opposite directions (one says rise, the other fall);
  * two level calls oppose when their targets sit on opposite sides of the metric's trailing-7-day mean (the observation
    both coaches were shown); a target ON the mean, or a direction call against a level call, is not a dispute.
A dispute that does not oppose its target, names another metric or an unknown call, cites nothing, or whose rationale
fails the brief's own text checks (numbers, private-activity words, people, the sensitivity screen) is dropped.

EACH SIDE IS A LEDGER CALL. The disputing side is filed through ``public_brief.file_call`` exactly like any brief call
(``validate_filing`` must call it GRADEABLE, ``source = public_brief``, so it is dark with every brief call), over the
target call's own window; the earlier side is the earlier coach's call, already filed. The existing evaluator grades
both: there is no new grader and no verdict stored here. This is not the ``ENSEMBLE#docket`` (no docket row, no
docket throttle, no ``dispute_docket`` source).

THE RECORD. ``COACH#<later coach> / PUBLIC_BRIEF#<cycle>#DISPUTE#<pair>#<metric>`` holds both prediction ids, both
rendered claims, the observation ids each side cited, the frozen opposition criterion and a provenance stamp derived
from BOTH briefs. It is written once (conditional put) and never rewritten: the criterion is frozen at filing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from common import narrative_provenance as NP, public_brief_policy as POL

MAX_DISPUTES = 2  # per coach per cycle
OPPOSITE_DIRECTION = "opposite_direction"
OTHER_SIDE_OF_MEAN = "other_side_of_trailing_7_day_mean"


def pair_key(coach_a: str, coach_b: str) -> str:
    """Order-independent: the same two coaches on the same metric are one dispute per cycle."""
    return "__".join(sorted((str(coach_a), str(coach_b))))


# ── what a later coach is shown ─────────────────────────────────────────────────────────────
def shared_calls(coach_id: str, brief: Optional[dict]) -> list:
    """The calls of one coach's brief that a later coach may dispute: its own predictions (never its disputes), from a
    brief whose provenance is publishable."""
    if not isinstance(brief, dict) or not NP.is_publishable(brief):
        return []
    windows = {c.get("prediction_id"): c.get("evaluation_window_days") for c in brief.get("evaluation_criteria") or []}
    out = []
    for p in brief.get("predictions") or []:
        if not isinstance(p, dict) or p.get("against") or not p.get("prediction_id"):
            continue
        window = p.get("window_days") or windows.get(p.get("prediction_id"))
        if p.get("kind") not in ("direction", "level") or not window:
            continue
        out.append(
            {
                "coach_id": coach_id,
                "item": p.get("id"),
                "prediction_id": p["prediction_id"],
                "claim": p.get("claim"),
                "metric": p.get("metric"),
                "kind": p["kind"],
                "direction": p.get("direction"),
                "target": p.get("target"),
                "window_days": int(window),
                "cites": list(p.get("cites") or []),
                "brief": brief,
            }
        )
    return out


def offered(others: list, metrics: list) -> list:
    """The earlier calls on metrics this coach also reads, each with a ref (x1, x2, ...) the model names."""
    shown = [dict(c) for c in others or [] if c.get("metric") in set(metrics or [])]
    for n, c in enumerate(shown, 1):
        c["ref"] = f"x{n}"
    return shown


def others_block(targets: list, personas: dict) -> str:
    if not targets:
        return ""
    lines = [
        "Other coaches' calls this cycle on metrics you also read. You may dispute one ONLY if your reading of the same "
        "facts points the other way:"
    ]
    for t in targets:
        name = (personas.get(t["coach_id"]) or {}).get("name") or "Another coach"
        lines.append(f"{t['ref']} | {name} | {t['claim']}")
    return "\n".join(lines)


def prompt_rules(targets: list) -> str:
    if not targets:
        return ""
    return (
        '- "disputes": only if other coaches\' calls are shown: up to '
        f'{MAX_DISPUTES} of {{"against": its ref (x1...), "kind": the same kind as that call, "direction": "up"|"down" '
        '(direction only — the opposite of theirs), "target": number (level only — on the other side of the last-7-day '
        'mean from theirs), "confidence", "rationale", "cites": [observation ids]}. Otherwise [].\n'
    )


# ── the opposition rule ─────────────────────────────────────────────────────────────────────
def _side(kind: str, direction: Any, target: Any, mean: Any) -> int:
    if kind == "direction":
        return {"up": 1, "down": -1}.get(direction, 0)
    try:
        t, m = float(target), float(mean)
    except (TypeError, ValueError):
        return 0
    return (t > m) - (t < m)


def opposition(theirs: dict, mine: dict, mean: Any) -> Optional[str]:
    """The rule under which ``mine`` opposes ``theirs`` on the same metric, or None when it does not."""
    if theirs.get("metric") != mine.get("metric") or theirs.get("kind") != mine.get("kind"):
        return None
    a = _side(theirs["kind"], theirs.get("direction"), theirs.get("target"), mean)
    b = _side(mine["kind"], mine.get("direction"), mine.get("target"), mean)
    if a == 0 or b == 0 or a == b:
        return None
    return OPPOSITE_DIRECTION if mine["kind"] == "direction" else OTHER_SIDE_OF_MEAN


# ── the record ──────────────────────────────────────────────────────────────────────────────
def provenance(own_provenance: dict, theirs_brief: dict, metric: str, producer: str) -> dict:
    """Derived from BOTH briefs: the metric's families, plus everything each brief was made from."""
    families = POL.families_for([metric]) + [POL.PERSONA_FAMILY, POL.LEDGER_FAMILY]
    return NP.stamp(families, producer=producer + ".dispute", upstream=[{NP.PROVENANCE_KEY: own_provenance}, theirs_brief])


def _side_record(cid: str, item: Any, pid: Any, claim: Any, cites: Any, ev: dict) -> dict:
    return {
        "coach_id": cid,
        "item": item,
        "prediction_id": pid,
        "claim": claim,
        "cited_observations": sorted(cites or []),
        "evaluation": {k: ev.get(k) for k in ("type", "metric", "window_start", "window_end", "threshold", "tolerance")},
    }


def dispute_row(coach_id: str, cycle: str, mine: tuple, theirs: dict, rule: str, mean: Any, prov: dict) -> dict:
    """``mine`` is ``(item_id, pred, ledger_row)`` of the disputing call; ``theirs`` the shared call it opposes."""
    item_id, pred, row = mine
    pair = pair_key(theirs["coach_id"], coach_id)
    theirs_ev: dict = next(
        (c for c in (theirs["brief"].get("evaluation_criteria") or []) if c.get("prediction_id") == theirs["prediction_id"]), {}
    )
    return {
        "pk": f"COACH#{coach_id}",
        "sk": POL.dispute_sk(cycle, pair, pred["metric"]),
        "coach_id": coach_id,
        "brief_cycle": cycle,
        "pair": pair,
        "metric": pred["metric"],
        "criterion": {
            "rule": rule,
            "kind": pred["kind"],
            "trailing_7_day_mean": mean if rule == OTHER_SIDE_OF_MEAN else None,
            "window_days": int(pred["window_days"]),
        },
        "sides": [
            _side_record(
                theirs["coach_id"],
                theirs["item"],
                theirs["prediction_id"],
                theirs["claim"],
                theirs["cites"],
                theirs_ev,
            ),
            _side_record(coach_id, item_id, row["prediction_id"], row["claim_natural"], pred["cites"], row.get("evaluation") or {}),
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        NP.PROVENANCE_KEY: prov,
    }
