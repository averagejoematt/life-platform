"""selection_live.py — the selection engine's LIVE policy (#5861 L3): progression, individual response and recoverability
first. It runs ONLY when the exercise library is `approved` (`selection_engine.mode() == "live"`); while it is `proposed`
the engine's shadow path is the #5773/#5857 code, unchanged, byte for byte (tests/test_selection_fatigue_5861.py).

WHAT CHANGES UNDER LIVE (owner brief 2026-11-12 §6/§7; epic #5861 rulings revised the same day)

  1. GATES ARE READ. A locking gate is locked unless #5772's weekly evaluation (`EXGATE#EVAL#`, read by
     `block_design_review.load_gate_eval_failsoft`) says `unlocked` for this movement. FAIL-CLOSED: no evaluation, a stale
     one (older than two weekly runs) or a failed read locks every gate, exactly as before.
  2. A SLOT NAMES ITS OBJECTIVE (`SLOT_OBJECTIVES`, default `hypertrophy` for every accessory slot today). Its tier is
     `quality_rubric.objective_tier(entry, objective, target)` (L1's contract) — with a local fallback to the library's
     `hypertrophy[]` rows (hypertrophy) or `ratings[objective].tier` until L1 lands. A movement with no rating for the
     objective (`None`, not applicable) is never a candidate for that slot — never forced into an objective.
  3. HOLD WHILE IT PROGRESSES, ROTATE FOR A NAMED REASON. The slot's previous variant (the rotation ledger) is HELD unless
     a trigger fires, and the trigger is recorded (`ROTATION_TRIGGERS`). The fixed three-week cadence and ruling B's
     "sole S/A member" hold no longer force change under live; the shadow path keeps them.
  4. WITHIN-WEEK REPETITION WHEN IT HELPS. A movement another slot serves this week is still passed over when a same-band
     peer is open (no pointless duplication — `week_repeat_avoided`); when the best band has no unserved member, a second
     weekly exposure of the best movement beats dropping a band (`repeat_beneficial`), up to `MAX_WEEKLY_EXPOSURES`.
  5. STIMULUS-TO-FATIGUE. Inside the pool: recent repeated discomfort on the movement first (it ranks last), then his N=1
     fit (individual stimulus and response), then the movement's fatigue cost (`fatigue_cost`, heuristic — machines and
     cables beat free weights at EQUAL fit for a hypertrophy slot; heavier when the fatigue model flags axial stacking),
     then slot variety, then tier. The free-weight compound floor (`week_commitments`) keeps free weights for strength
     and competence.

THE CONDITIONING SEAM (L4). A slot whose objective is `conditioning` is ranked by `objective_tier(..., "conditioning")`
like any other; `CONDITIONING_SLOT_SEAM` names where a conditioning day's slots join (`slot_objectives` in the library's
`selection_policy`, read live only). No slot is conditioning today.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ISSUE = "#5861"
OBJECTIVES = ("hypertrophy", "strength", "functional", "conditioning", "mobility")
DEFAULT_OBJECTIVE = "hypertrophy"
SLOT_OBJECTIVES: dict[str, str] = {
    "shoulders_arms.farmers_walk": "functional",  # an owner pin (B3): recorded, never re-picked
    "lower_volume.kettlebell_swing": "functional",  # an owner pin (2026-11-11): recorded, never re-picked
}
"""Per slot, the objective it is ranked for (`DEFAULT_OBJECTIVE` otherwise). A library `selection_policy.slot_objectives`
entry overrides it (data, not code) — the L4 conditioning seam."""
CONDITIONING_SLOT_SEAM = "library selection_policy.slot_objectives[<role>.<slot>] = 'conditioning' (L4 cardio_model, #5861)"

MAX_WEEKLY_EXPOSURES = 2  # heuristic: a movement serves at most two slots a week (two exposures, different days)
MAX_HOLD_WEEKS = 12  # heuristic, owner brief: primaries ~6-12 weeks; a held accessory stays while it progresses
ROTATION_TRIGGERS: dict[str, str] = {
    "stall": "no new best e1RM over three or more exposures at working effort, or regressing (fatigue_model trend)",
    "pain": "a pain-class note excludes it (#5806)",
    "discomfort": "two discomfort-class notes on it inside 14 days (fatigue_model, heuristic)",
    "equipment": "not available at home_gym (inventory, learned unavailability, the charter's not_available list)",
    "no_longer_servable": "a locked gate, not-for-you-now, the catalog, or the weekly floor now keeps it out of the slot",
    "pool_change": "a better band opened for the slot (a gate unlocked, a movement added)",
    "adherence": "he swaps it out (two or more swap notes in the overlay)",
    "fatigue": "the fatigue model names it (redundant axial stacking)",
    "owner_request": "the owner's block design approval names a different movement",
    "block_end_review": f"held {MAX_HOLD_WEEKS}+ weeks and not progressing at a new block",
}
"""Every reason a held slot may rotate under live. Nothing else rotates it — never a calendar alone."""
HOLD_REASONS = {
    "progressing": "progressing — the latest top set is his best in the window",
    "step_due": "the prescription held still at an easy RPE — the load steps, the movement stays",
    "unknown": "no rotation trigger (too few exposures to judge a trend)",
}
FATIGUE_COST_BASIS = (
    "heuristic: +1 compound, +1 free weight or bodyweight (stability + systemic cost), +1 moderate/high spinal load; "
    "+2 more on a high spinal load while the fatigue model flags axial stacking"
)
LIVE_PICK_KEYS = ("objective", "fatigue_cost", "discomfort", "trend", "rotation", "repeat")


# ── facts per movement ────────────────────────────────────────────────────────
def objective_of(slot_id: str, lib: dict[str, Any] | None) -> str:
    over = (((lib or {}).get("selection_policy") or {}).get("slot_objectives") or {}).get(slot_id)
    return over if over in OBJECTIVES else SLOT_OBJECTIVES.get(slot_id, DEFAULT_OBJECTIVE)


def objective_tier(entry: dict[str, Any], objective: str, muscle: str | None) -> str | None:
    """The movement's tier for the slot's objective (L1's `quality_rubric.objective_tier` when it exists; else the local
    fallback). None = not applicable to the objective. Hypertrophy keeps today's per-muscle row semantics (a sub-target
    counts) and an unrated row is `selection_engine.UNRATED_TIER`, as in shadow."""
    from training import quality_rubric, selection_engine as se

    fn = getattr(quality_rubric, "objective_tier", None)
    if objective == DEFAULT_OBJECTIVE:
        if callable(fn):
            tiers = [fn(entry, objective, r.get("target")) for r in se._rows_for(entry, str(muscle or ""))]
            ranked = sorted((t for t in tiers if t in se.TIER_RANK), key=lambda t: se.TIER_RANK[t])
            if ranked:
                return ranked[0]
        return se.tier_for(entry, str(muscle or ""))
    t = fn(entry, objective, muscle) if callable(fn) else (((entry.get("ratings") or {}).get(objective) or {}).get("tier"))
    return t if t in se.TIER_RANK else None


def fatigue_cost(entry: dict[str, Any], stacking: bool = False) -> int:
    """`FATIGUE_COST_BASIS` — a categorical cost, never a measured one."""
    spinal = (entry.get("joint_stress") or {}).get("spinal_load")
    cost = int(entry.get("job") == "compound") + int(entry.get("resistance_profile") in ("free_weight", "bodyweight"))
    cost += int(spinal in ("moderate", "high"))
    return cost + (2 if stacking and spinal == "high" else 0)


def _signals_for(entry: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    return (policy.get("signals") or {}).get(str(entry.get("template_id") or "").upper()) or {}


def decorate(c: dict[str, Any], entry: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    """The live facts on one candidate (objective tier, fatigue cost, discomfort, trend), or None when the movement is not
    applicable to the slot's objective."""
    policy = ctx["policy"]
    objective = objective_of(ctx["slot_id"], ctx["lib"])
    tier = objective_tier(entry, objective, ctx["spec"]["muscle"])
    if tier is None:
        return None
    sig = _signals_for(entry, policy)
    from training.fatigue_model import THRESHOLDS

    hurts = int(sig.get("discomfort_sessions") or 0) >= THRESHOLDS["discomfort_sessions"]["value"]
    return c | {
        "tier": tier,
        "objective": objective,
        "fatigue_cost": fatigue_cost(entry, bool(policy.get("stacking"))),
        "discomfort": hurts,
        "trend": sig.get("trend") or "unknown",
    }


def gate_locked(entry: dict[str, Any], lib: dict[str, Any], mid: str, gate_eval: dict[str, Any] | None) -> list[str]:
    """The entry's locking gates that the stored evaluation does NOT read `unlocked` for this movement. No evaluation =
    every locking gate (fail-closed)."""
    from training import block_design_review as bdr, selection_engine as se

    gates = se._locking_gates(entry, lib)
    if not isinstance(gate_eval, dict):
        return gates
    return [g for g in gates if bdr.gate_state(gate_eval, g, mid).get("state") != "unlocked"]


def rank_key(c: dict[str, Any], recent: set[str], slot_last: dict[str, int], pool: tuple[str, ...]) -> tuple[Any, ...]:
    """Inside the pool: discomfort last, then N=1 fit, then fatigue cost, then this slot's variety, then tier."""
    from training import selection_engine as se

    ck = c.get("catalog_key") or ""
    inside = c["tier"] in pool
    tier = se.TIER_RANK[c["tier"]]
    return (
        0 if inside else 1,
        0 if inside else tier,
        c.get("discomfort", False),
        -c["n1"]["score"],
        c.get("fatigue_cost", 0),
        slot_last.get(ck, -1),
        tier,
        ck in recent,
        c["novel"],
        -c["exposures"],
        se.EVIDENCE_RANK.get(str(c.get("evidence")), len(se.EVIDENCE_RANK)),
        c["movement_id"],
    )


# ── hold or rotate ────────────────────────────────────────────────────────────
def previous_variant(slot_last: dict[str, int]) -> str | None:
    """What this slot served most recently in an earlier phase (the rotation ledger), or None."""
    return max(slot_last, key=lambda k: (slot_last[k], k)) if slot_last else None


def held_weeks(rows: list[dict[str, Any]] | None, position: dict[str, Any] | None, slot_id: str, prev: str) -> int:
    """How many weeks `prev` has served this slot without a break, back from the phase before this one (ledger rows only:
    this block and the one before)."""
    from training import variant_rotation as vr

    served: list[tuple[int, str, int]] = []
    for r in rows or []:
        if not str(r.get("sk") or "").endswith(f"#{slot_id}"):
            continue
        blk = int(r.get("block") or str(r.get("sk") or "ROTATION#B000#").split("#")[1][1:] or 0)
        for k, v in r.items():
            if k.startswith("phase_") and isinstance(v, dict) and v.get("variant"):
                if position and blk == position.get("block") and k == f"phase_{position.get('phase')}":
                    continue
                weeks = v.get("weeks") or [1, vr.rotate_every_weeks()]
                served.append((blk * 100 + int(k.split("_", 1)[1] or 0), str(v["variant"]), int(weeks[-1]) - int(weeks[0]) + 1))
    total = 0
    for _o, variant, n in sorted(served, reverse=True):
        if variant != prev:
            break
        total += n
    return total


def _trigger(prev: str, eligible: list[dict[str, Any]], excluded: list[dict[str, Any]], pool: tuple[str, ...], ctx: dict) -> tuple:
    """(trigger code | None, the previous candidate | None, its trend) for the slot's previous variant."""
    codes = {"pain_swap": "pain", "equipment": "equipment"}
    gone = next((x for x in excluded if x.get("catalog_key") == prev), None)
    if gone:
        return codes.get(gone["code"], "no_longer_servable"), None, None
    c = next((x for x in eligible if x.get("catalog_key") == prev), None)
    if c is None:
        return "no_longer_servable", None, None
    policy = ctx["policy"]
    swaps = {s.get("movement_id") for s in policy.get("fatigue_swaps") or []}
    trend = c.get("trend") or "unknown"
    if c.get("discomfort"):
        return "discomfort", c, trend
    if c["movement_id"] in swaps:
        return "fatigue", c, trend
    if trend in ("stalled", "regressing"):
        return "stall", c, trend
    if (c["n1"].get("components") or {}).get("swap_out") == -1:
        return "adherence", c, trend
    if c["tier"] not in pool:
        return "pool_change", c, trend
    pos = policy.get("position") or {}
    if int(pos.get("phase") or 0) == 1 and int(pos.get("step") or 0) > 0 and trend != "progressing":
        if held_weeks(policy.get("rows"), pos, ctx["slot_id"], prev) >= MAX_HOLD_WEEKS:
            return "block_end_review", c, trend
    return None, c, trend


def _choose(ranked: list[dict[str, Any]], counts: Counter, skip: str | None) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """The best candidate under the live repetition rule (module doc 4), and the repetition record."""
    pool = [c for c in ranked if c.get("catalog_key") != skip] or ranked
    if not pool:
        return None, None
    best = pool[0]
    n = counts[best.get("catalog_key") or ""]
    if n == 0:
        return best, None
    peer = next((c for c in pool if c["tier"] == best["tier"] and counts[c.get("catalog_key") or ""] == 0), None)
    if peer:
        why = f"{best['title']} already serves another slot this week; {peer['title']} is a same-band peer — no pointless duplication"
        return peer, {"code": "week_repeat_avoided", "why": why}
    if n < MAX_WEEKLY_EXPOSURES:
        why = f"the best band has no unserved member: a second weekly exposure of {best['title']} beats a lower-band movement"
        return best, {"code": "repeat_beneficial", "why": why}
    rest = next((c for c in pool if counts[c.get("catalog_key") or ""] < MAX_WEEKLY_EXPOSURES), best)
    return rest, {"code": "week_repeat_cap", "why": f"{best['title']} already serves {n} slots this week (cap {MAX_WEEKLY_EXPOSURES})"}


def select_slot(slot: dict[str, Any], ctx: dict[str, Any], recent: set[str]) -> dict[str, Any]:
    """One slot under the live policy: hold the previous variant unless a trigger fires, else the best by `rank_key`, with
    the repetition rule over the week's counts (`ctx['policy']['week_counts']`)."""
    from training import selection_engine as se

    eligible, excluded = se.candidates(ctx)
    pool = se.pool_tiers(eligible)
    ranked = sorted(eligible, key=lambda c: rank_key(c, recent, ctx.get("slot_last") or {}, pool))
    counts: Counter = ctx["policy"]["week_counts"]
    prev = previous_variant(ctx.get("slot_last") or {})
    base = {"slot_id": slot["slot_id"], "role": slot["role"], "incumbent": slot["incumbent"], "spec": ctx["spec"], "floor": ctx["floor"]}
    if not ranked:
        return {
            **base,
            "pick": None,
            "reason": "no eligible library candidate — the template accessory serves",
            "ranked": [],
            "excluded": excluded,
        }
    trigger, held, trend = _trigger(prev, eligible, excluded, pool, ctx) if prev else (None, None, None)
    repeat = None
    if held is not None and trigger is None and counts[prev or ""] < MAX_WEEKLY_EXPOSURES:
        chosen = held
        rotation = {"action": "hold", "previous": prev, "reason": HOLD_REASONS.get(str(trend), HOLD_REASONS["unknown"]), "trend": trend}
        if counts[prev or ""]:
            repeat = {"code": "repeat_beneficial", "why": f"{held['title']} is held here while it progresses and serves another slot too"}
    else:
        chosen, repeat = _choose(ranked, counts, prev if trigger else None)
        if prev and trigger is None:  # held, but already at the weekly cap
            trigger = "week_repeat_cap"
        rotation = (
            {"action": "rotate", "previous": prev, "trigger": trigger, "why": ROTATION_TRIGGERS.get(str(trigger), "weekly repetition cap")}
            if prev
            else {"action": "initial", "previous": None, "why": "no earlier phase in the ledger for this slot"}
        )
    assert chosen is not None
    skipped = [c for c in ranked[: ranked.index(chosen)] if counts[c.get("catalog_key") or ""] > 0]
    pick = chosen | {
        "c_reason": se.c_reason(chosen, excluded, skipped=skipped, pooled=[c for c in eligible if c["tier"] in pool]),
        "novel_terms": se._novel_terms(chosen),
        "week_repeat": None,
        "rotation": rotation,
        "repeat": repeat,
    }
    above = [x for x in excluded if se.TIER_RANK[x["tier"]] < se.TIER_RANK[chosen["tier"]]]
    return {
        **base,
        "pick": pick,
        "top_band": se.top_band(pick, ranked, pool),
        "fallbacks": se.fallbacks(pick, ranked, novel_budget=se.NOVELTY_PER_SLOT - int(pick["novel"])),
        "ranked": [c["movement_id"] for c in ranked],
        "above_pick": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why")} for x in above],
        "excluded": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why", "gates")} for x in excluded],
    }


# ── the policy (built once per draft, live only) ─────────────────────────────
def build_policy(
    lib: dict[str, Any],
    *,
    position: dict[str, Any] | None,
    rows: list[dict[str, Any]] | None,
    block_workouts: list[dict[str, Any]] | None,
    as_of: str | None,
    gate_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Everything the live policy reads, once: the gate evaluation (`{state, row}`), each movement's trend and discomfort
    and the fatigue model's swaps (from the Hevy record), the ledger rows and the position."""
    from training import fatigue_model as fm

    signals, swaps, stacking = None, [], False
    if block_workouts is not None and as_of:
        signals = fm.movement_signals(block_workouts, as_of=as_of)
        found = fm.axial_stacking(block_workouts, fm.library_index(lib), as_of=as_of)
        stacking = bool(found)
        swaps = [{"movement_id": f["exposures"][-1]["movement_id"], "why": f["finding"]} for f in found]
    ge = gate_eval if isinstance(gate_eval, dict) else {"state": "not_read", "row": None}
    return {
        "issue": ISSUE,
        "gate_eval": ge.get("row") if ge.get("state") == "read" else None,
        "gate_eval_state": ge.get("state"),
        "signals": signals,
        "signals_state": "read" if signals is not None else "not_read (every trend unknown: holds, never a stall rotation)",
        "fatigue_swaps": swaps,
        "stacking": stacking,
        "rows": rows,
        "position": position,
        "week_counts": Counter(),
    }


def summary(policy: dict[str, Any]) -> dict[str, Any]:
    """The live policy's record on the selection (no rows, no counts)."""
    return {
        "issue": ISSUE,
        "gates": f"evaluated ({policy.get('gate_eval_state')}); anything but a fresh read locks every gate",
        "signals": policy.get("signals_state"),
        "stacking": policy.get("stacking"),
        "fatigue_swaps": policy.get("fatigue_swaps"),
        "rotation_triggers": sorted(ROTATION_TRIGGERS),
        "max_weekly_exposures": MAX_WEEKLY_EXPOSURES,
        "max_hold_weeks": MAX_HOLD_WEEKS,
        "fatigue_cost": FATIGUE_COST_BASIS,
    }
