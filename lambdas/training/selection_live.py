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

SYSTEMIC_REGRESSION_MIN = 4  # heuristic: four or more lifts stalling/regressing at once (and half of all judged) is systemic
MAX_NEW_PER_WEEK = 2  # heuristic: at most two new-to-him movements enter in one week (learning cost, soreness, load-finding)
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
    "upgrade_waits": "a better-rated movement is open, but an upgrade waits for the next block's first phase — no mid-block "
    "swap of a working lift (#5861 L6)",
    "systemic_regression": "most of his lifts are stalling or regressing together — systemic fatigue (sleep, recovery, the "
    "deficit), not this movement: volume comes down (the fatigue model), the movement stays (#5861 L6, heuristic)",
    "progressing": "progressing — the latest top set is his best in the window",
    "step_due": "the prescription held still at an easy RPE — the load steps, the movement stays",
    "unknown": "no rotation trigger (too few exposures to judge a trend)",
}
FATIGUE_COST_BASIS = (
    "heuristic: +1 compound, +1 free weight or bodyweight (stability + systemic cost), +1 moderate/high spinal load; "
    "+2 more on a high spinal load while the fatigue model flags axial stacking"
)
LIVE_PICK_KEYS = ("objective", "canonical", "fatigue_cost", "discomfort", "trend", "rotation", "repeat", "provisional")
LIVE_GATES_SOURCE = "#5772's stored evaluation (#5861, live): only `unlocked` opens; no fresh evaluation = locked"


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
            if ((entry.get("ratings") or {}).get(objective) or {}).get("tier", "") is None:
                return None  # L1: hypertrophy not applicable (cardio, carries, control work) — never read as D under live
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
    if tier is None or not same_trunk_job(entry, ctx):
        return None
    sig = _signals_for(entry, policy)
    from training.fatigue_model import THRESHOLDS

    hurts = int(sig.get("discomfort_sessions") or 0) >= THRESHOLDS["discomfort_sessions"]["value"]
    return c | {
        "tier": tier,
        "objective": objective,
        "canonical": family(c.get("movement_id"), c.get("catalog_key"), ctx["lib"]),
        "fatigue_cost": fatigue_cost(entry, bool(policy.get("stacking"))),
        # rubric 3.2.0 (FIX2-DATA): an unreviewed rating is `provisional` — at an equal tier a reviewed row ranks first
        "provisional": bool(((entry.get("ratings") or {}).get(objective) or {}).get("provisional")),
        "discomfort": hurts,
        "trend": sig.get("trend") or "unknown",
    }


def same_trunk_job(entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """#5861 L6: a trunk slot keeps its TRUNK FUNCTION (L1's `trunk_function`: loaded flexion, anti-extension, anti-rotation,
    ...). The pattern table files rotation, twists and side bends under trunk flexion, so a crunch slot could serve a torso
    rotation machine; the job is the function, not the word. A slot whose incumbent has no trunk function is unaffected."""
    from training import selection_engine as se

    inc = (se.xl.movements(ctx["lib"]).get(str(ctx["spec"].get("incumbent_library_id") or "")) or {}).get("trunk_function")
    return not inc or not entry.get("trunk_function") or entry.get("trunk_function") == inc


def gate_locked(entry: dict[str, Any], lib: dict[str, Any], mid: str, gate_eval: dict[str, Any] | None) -> list[str]:
    """The entry's locking gates that the stored evaluation does NOT read `unlocked` for this movement. No evaluation =
    every locking gate (fail-closed)."""
    from training import block_design_review as bdr, selection_engine as se

    gates = se.locked_gates(entry, lib)
    if not isinstance(gate_eval, dict):
        return gates
    return [g for g in gates if bdr.gate_state(gate_eval, g, mid).get("state") != "unlocked"]


def gates(lid: str, entry: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """The engine's gate predicate: the live evaluation (fail-closed) under a policy, else the #5773 rule (all locked)."""
    from training import selection_engine as se

    if ctx.get("policy"):
        return gate_locked(entry, ctx["lib"], lid, ctx["policy"].get("gate_eval"))
    return se.locked_gates(entry, ctx["lib"])


def held(p: dict[str, Any]) -> bool:
    """A slot the live policy HELD keeps its movement — the lengthened pass never undoes a hold. Never true in shadow."""
    return ((p.get("pick") or {}).get("rotation") or {}).get("action") == "hold"


def count_pick(p: dict[str, Any], policy: dict[str, Any] | None, ctx: dict[str, Any]) -> None:
    """Count the pick toward the week's repetition rule; an owner pin or approval records its own rotation decision
    (`owner_request` when it names a movement other than the slot's previous variant). No policy (shadow): nothing."""
    if policy is None:
        return
    pick = p["pick"]
    policy["week_counts"][pick.get("canonical") or family(pick.get("movement_id"), pick.get("catalog_key"), ctx["lib"])] += 1
    if (p.get("owner_pin") or {}).get("state") == "held" and "rotation" not in pick:
        prev = previous_variant(ctx.get("slot_last") or {})
        same = prev in (None, pick["catalog_key"])
        pick["rotation"] = {"action": "hold" if same else "rotate", "previous": prev, "trigger": None if same else "owner_request"}


def decision(chosen: dict[str, Any]) -> dict[str, Any]:
    """The rotation slot's `rotation_decision` (read by `week_commitments._live_hold`) — {} for a shadow pick."""
    rot = (chosen.get("pick") or {}).get("rotation")
    return {"rotation_decision": rot} if rot else {}


def line_suffix(p: dict[str, Any]) -> str:
    """The draft rationale's words for a live pick's hold/rotation and repetition ("" for a shadow pick)."""
    rot, rep = p.get("rotation") or {}, p.get("repeat") or {}
    out = f" — {rot.get('action')}: {rot.get('reason') or rot.get('trigger') or rot.get('why')}" if rot else ""
    return out + (f" — {rep['code']}: {rep['why']}" if rep.get("code") else "")


def rank_key(c: dict[str, Any], recent: set[str], slot_last: dict[str, int], pool: tuple[str, ...]) -> tuple[Any, ...]:
    """Inside the pool: discomfort last, then N=1 fit, then fatigue cost, then this slot's variety, then tier."""
    from training import selection_engine as se

    ck = c.get("catalog_key") or ""
    inside = c["tier"] in pool and not c.get("provisional")  # #5861 FIX6 ruling 16: a provisional rating is never proof of suitability
    tier = se.TIER_RANK[c["tier"]]
    return (
        0 if inside else 1,
        0 if inside else tier,
        c.get("discomfort", False),
        -c["n1"]["score"],
        c.get("fatigue_cost", 0),
        slot_last.get(ck, -1),
        tier,
        c.get("provisional", False),
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
        if policy.get("systemic_regression"):
            return None, c, "systemic_regression"  # #5861 L6: a week where everything stalls is fatigue, not novelty-hunger
        return "stall", c, trend
    if (c["n1"].get("components") or {}).get("swap_out") == -1:
        return "adherence", c, trend
    pos = policy.get("position") or {}
    if c["tier"] not in pool and any(x["tier"] in pool and _open(x, policy) for x in eligible):
        # #5861 L6: only when a better band is SERVABLE this week (not every member at its cap), and only at a block's first
        # phase — an upgrade is a block-start decision (the block design review's), never a mid-block swap of a working lift
        if int(pos.get("phase") or 1) == 1:
            return "pool_change", c, trend
        return None, c, "upgrade_waits"
    if int(pos.get("phase") or 0) == 1 and int(pos.get("step") or 0) > 0 and trend != "progressing":
        if held_weeks(policy.get("rows"), pos, ctx["slot_id"], prev) >= MAX_HOLD_WEEKS:
            return "block_end_review", c, trend
    return None, c, trend


def _open(c: dict[str, Any], policy: dict[str, Any]) -> bool:
    """The candidate can still take a slot this week under the repetition cap (`MAX_WEEKLY_EXPOSURES`)."""
    return (policy.get("week_counts") or Counter())[_fam(c)] < MAX_WEEKLY_EXPOSURES


def family(movement_id: Any, catalog_key: Any, lib: dict[str, Any] | None) -> str:
    """The movement's CANONICAL family (L1's alias layer, `exercise_library.canonical_of`): the within-week repetition rule
    compares families, so an alias or a grip variant of a movement already served is a repeat, not a peer. Falls back to
    the catalog key when the library cannot place it."""
    from training import selection_engine as se  # the ONE sanctioned library reader (tests/test_exercise_library_5769.py)

    return str((se.xl.canonical_of(lib or {}, str(movement_id)) if movement_id else None) or catalog_key or movement_id or "")


def _fam(c: dict[str, Any]) -> str:
    return str(c.get("canonical") or c.get("catalog_key") or "")


def _choose(ranked: list[dict[str, Any]], counts: Counter, skip: str | None) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """The best candidate under the live repetition rule (module doc 4), and the repetition record."""
    pool = [c for c in ranked if c.get("catalog_key") != skip] or ranked
    if not pool:
        return None, None
    best = pool[0]
    n = counts[_fam(best)]
    if n == 0:
        return best, None
    peer = next((c for c in pool if c["tier"] == best["tier"] and counts[_fam(c)] == 0), None)
    if peer:
        why = f"{best['title']} already serves another slot this week; {peer['title']} is a same-band peer — no pointless duplication"
        return peer, {"code": "week_repeat_avoided", "why": why}
    if n < MAX_WEEKLY_EXPOSURES:
        why = f"the best band has no unserved member: a second weekly exposure of {best['title']} beats a lower-band movement"
        return best, {"code": "repeat_beneficial", "why": why}
    rest = next((c for c in pool if counts[_fam(c)] < MAX_WEEKLY_EXPOSURES), best)
    return rest, {"code": "week_repeat_cap", "why": f"{best['title']} already serves {n} slots this week (cap {MAX_WEEKLY_EXPOSURES})"}


def _novelty_cap(chosen: dict, ranked: list[dict], policy: dict, skip: str | None, repeat: Any) -> tuple[dict, Any]:
    """#5861 L6: `MAX_NEW_PER_WEEK` — past the week's new-movement budget a new pick yields to the best familiar candidate the
    repetition cap still allows (said so); with none it stands. Every new pick served is counted."""
    if chosen.get("novel") and policy.get("novel_count", 0) >= MAX_NEW_PER_WEEK:
        alt = next((c for c in ranked if not c.get("novel") and c.get("catalog_key") != skip and _open(c, policy)), None)
        if alt is not None:
            why = f"{chosen['title']} would be the week's {MAX_NEW_PER_WEEK + 1}th new movement; {alt['title']} is familiar"
            return alt, {"code": "novelty_budget", "why": why}
    if chosen.get("novel"):
        policy["novel_count"] = policy.get("novel_count", 0) + 1
    return chosen, repeat


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
    defer = held if trigger in DEFERRABLE_TRIGGERS and held is not None else None  # a discretionary rotation can wait a week
    repeat = None
    if held is not None and trigger is None and counts[_fam(held)] < MAX_WEEKLY_EXPOSURES:
        chosen = held
        rotation = {"action": "hold", "previous": prev, "reason": HOLD_REASONS.get(str(trend), HOLD_REASONS["unknown"]), "trend": trend}
        if counts[_fam(held)]:
            repeat = {"code": "repeat_beneficial", "why": f"{held['title']} is held here while it progresses and serves another slot too"}
    else:
        chosen, repeat = _choose(ranked, counts, prev if trigger else None)
        chosen, repeat = _novelty_cap(chosen, ranked, ctx["policy"], prev if trigger else None, repeat)  # a hold is never "new"
        if prev and trigger is None:  # held, but already at the weekly cap
            trigger = "week_repeat_cap"
        rotation = (
            {"action": "rotate", "previous": prev, "trigger": trigger, "why": ROTATION_TRIGGERS.get(str(trigger), "weekly repetition cap")}
            if prev
            else {"action": "initial", "previous": None, "why": "no earlier phase in the ledger for this slot"}
        )
    assert chosen is not None
    out = _slot_result(base, chosen, rotation, repeat, (ranked, eligible, excluded, pool, counts))
    if defer is not None and defer is not chosen:
        why = f"{NOVELTY_HOLD} ({trigger} waits)"
        hold = {"action": "hold", "previous": prev, "reason": why, "trend": trend, "deferred_trigger": trigger}
        out["novelty_hold"] = _slot_result(base, defer, hold, None, (ranked, eligible, excluded, pool, counts))
    return out


def _slot_result(base: dict[str, Any], chosen: dict[str, Any], rotation: dict[str, Any], repeat: Any, env: tuple) -> dict[str, Any]:
    """One slot's selection record for `chosen` (the pick, its band, fallbacks and the ranking it came from)."""
    from training import selection_engine as se

    ranked, eligible, excluded, pool, counts = env
    skipped = [c for c in ranked[: ranked.index(chosen)] if counts[_fam(c)] > 0]
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


DEFERRABLE_TRIGGERS = ("stall", "adherence", "block_end_review", "pool_change")
"""Rotations that may WAIT a week for the novelty budget, in the order they keep a place inside it (a stall is a progression
problem now; an upgrade is never urgent). Pain, discomfort, equipment, no-longer-servable, fatigue, an owner request and the
weekly repetition cap are FORCED: the previous movement cannot serve, so they always rotate (and still count)."""
NOVELTY_HOLD = "novelty budget: the week already changes its quota of movements — this rotation waits"


def served_key(p: dict[str, Any], policy: dict[str, Any]) -> str | None:
    """What the slot SERVES this week under live (`selection_engine._live`): a budget hold (`novelty_serve`), else the pick — ONE
    authority (fix round 10, the ninth red team: "selection X — THIS phase serves Y" was the rotation ledger overriding the live
    pick; the ledger now only records what served)."""
    key = (p.get("pick") or {}).get("catalog_key")
    return p.get("novelty_serve") or key


def _eligible(p: dict[str, Any]) -> set[str]:
    key = (p.get("pick") or {}).get("catalog_key")
    if (p.get("owner_pin") or {}).get("state") == "held":
        return {key} if key else set()
    return {k for k in [key] + [f.get("catalog_key") for f in p.get("fallbacks") or []] if k}


def last_phase_key(p: dict[str, Any], policy: dict[str, Any]) -> str | None:
    """What the slot served LAST phase — the rotation ledger's previous phase (as `variant_rotation._slot_plan` reads it, the
    "New: replaces …" line's own reference), else the live rotation's previous variant."""
    from training import variant_rotation as vr

    pos = policy.get("position") or {}
    block, phase = int(pos.get("block") or 0), int(pos.get("phase") or 0)
    pb, pp = (block, phase - 1) if phase > 1 else (block - 1, int(pos.get("phases_per_block") or 2))
    led = vr._ledger_variant(policy.get("rows"), pb, p["slot_id"], pp) if pos and pb >= 1 else None
    return led or ((p.get("pick") or {}).get("rotation") or {}).get("previous")


RECENT_DAYS = 28  # heuristic: a movement performed in the last four weeks (this phase) is not new to him this week


def changes_served(p: dict[str, Any], policy: dict[str, Any], catalog: dict[str, Any] | None = None) -> bool:
    """The slot SERVES a movement this week that it did not serve last phase (`served_key` against `last_phase_key`, or a
    never-logged first pick) AND that he has not performed in the last RECENT_DAYS (when the record was read) — what the
    trainee meets as new this week: a "New: replaces" line and a load to find. A change made at the phase's start that he
    has done since is last week's novelty, not this week's."""
    served, prev = served_key(p, policy), last_phase_key(p, policy)
    if not served or p.get("pinned"):
        return False
    new = served != prev if prev else bool((p.get("pick") or {}).get("novel"))
    recent = policy.get("recent_tids")
    tid = str(((catalog or {}).get(served) or {}).get("hevy_template_id_hint") or "").upper()
    return new and not (recent is not None and tid and tid in recent)


def _change_rank(p: dict[str, Any]) -> int:
    rot = (p.get("pick") or {}).get("rotation") or {}
    return {t: n for n, t in enumerate(DEFERRABLE_TRIGGERS)}.get(str(rot.get("trigger")), len(DEFERRABLE_TRIGGERS))


def enforce_novelty(picked: list[dict[str, Any]], policy: dict[str, Any] | None, catalog: dict[str, Any] | None = None) -> list[str]:
    """IN PLACE, live only (`selection_engine.select_week`, after every slot): MAX_NEW_PER_WEEK covers EVERY movement the served
    week changes — ZERO on a declared short or adherence-dip week (fix round 10, the ninth red team: two new accessories in the
    week meant to rebuild routine; forced changes still serve). Second red team: the owner's real run served four new movements against a budget of two — the budget counted
    only never-logged picks, and the rotation ledger carried a shadow-era (#5075 calendar) phase decision forward, which
    `_live` serves whenever it is one of the pick's fallbacks. Now a change whose last-phase movement can still serve here
    (one of the slot's eligible movements) is OPTIONAL; any other is FORCED (pain, equipment, no longer servable) and keeps its
    place. Past the budget the optional changes wait, lowest priority first (a stall keeps its place longest; a calendar
    rotation the live policy never asked for waits first): the slot serves last phase's movement, said so. Returns the
    deferred slot ids."""
    if policy is None:
        return []
    changed = [i for i, p in enumerate(picked) if changes_served(p, policy, catalog)]

    def optional(i: int) -> bool:
        return last_phase_key(picked[i], policy) in _eligible(picked[i]) | {
            (picked[i].get("novelty_hold") or {}).get("pick", {}).get("catalog_key")
        }

    forced = [i for i in changed if not optional(i)]
    budget = 0 if policy.get("settle_week") else MAX_NEW_PER_WEEK  # fix round 10: a short or dip week rebuilds routine first
    room = max(0, budget - len(forced))
    deferred = []
    for i in sorted((i for i in changed if optional(i)), key=lambda i: (_change_rank(picked[i]), i))[room:]:
        p, prev = picked[i], last_phase_key(picked[i], policy)
        served = served_key(p, policy)
        hold = p.get("novelty_hold")
        p = {**hold} if hold and (hold.get("pick") or {}).get("catalog_key") == prev else p
        rot = dict((p.get("pick") or {}).get("rotation") or {})
        if NOVELTY_HOLD not in str(rot.get("reason") or ""):
            rot["reason"] = f"{rot.get('reason') or rot.get('why') or 'hold'} — {NOVELTY_HOLD}"
        rot["reason"] += f"; {served} waits, {prev} serves"
        picked[i] = p | {"pick": {**p["pick"], "rotation": rot}, "novelty_deferred": True, "novelty_serve": prev}
        deferred.append(p["slot_id"])
    for p in picked:
        p.pop("novelty_hold", None)  # the alternative is not part of the record
    policy["novelty"] = {"changed": len(changed), "forced": len(forced), "deferred": deferred, "budget": budget}
    return deferred


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

    signals, swaps, stacking, recent, settle = None, [], False, None, None
    if block_workouts is not None and as_of:
        from training import live_sequence

        settle = (live_sequence.week_plan(live_sequence.monday_of(str(as_of)[:10]), block_workouts, lib) or {}).get("mode")
        recent = _recent_tids(block_workouts, as_of)
        signals = fm.movement_signals(block_workouts, as_of=as_of)
        found = fm.axial_stacking(block_workouts, fm.library_index(lib), as_of=as_of)
        stacking = bool(found)
        swaps = [{"movement_id": f["exposures"][-1]["movement_id"], "why": f["finding"]} for f in found]
    ge = gate_eval if isinstance(gate_eval, dict) else {"state": "not_read", "row": None}
    trends = [v.get("trend") for v in (signals or {}).values() if v.get("trend") not in (None, "unknown")]
    down = sum(1 for t in trends if t in ("stalled", "regressing"))
    return {
        "issue": ISSUE,
        "gate_eval": ge.get("row") if ge.get("state") == "read" else None,
        "gate_eval_state": ge.get("state"),
        "signals": signals,
        "signals_state": "read" if signals is not None else "not_read (every trend unknown: holds, never a stall rotation)",
        "fatigue_swaps": swaps,
        "stacking": stacking,
        # #5861 L6 (heuristic): SYSTEMIC_REGRESSION_MIN or more judged lifts and at least half stalling or regressing together
        "systemic_regression": down >= SYSTEMIC_REGRESSION_MIN and down * 2 >= len(trends),
        "rows": rows,
        "position": position,
        "week_counts": Counter(),
        "recent_tids": recent,  # #5861 second red team: what he performed in RECENT_DAYS (the novelty budget's "new to him")
        "mild_pain": _mild_pain(block_workouts),  # #5861 FIX4: a mild (<= 3/10, not sharp) pain note keeps the movement
        "settle_week": settle,  # fix round 10: a short / dip week's mode — the novelty budget is zero (`enforce_novelty`)
    }


def _mild_pain(block_workouts: list[dict[str, Any]] | None) -> set[str]:
    from training.live_safety import mild_pain_tids

    return mild_pain_tids(block_workouts) if block_workouts else set()


def _recent_tids(block_workouts: list[dict[str, Any]], as_of: str) -> set[str]:
    from common.pacific_time import shift_day_key

    since = shift_day_key(str(as_of)[:10], -RECENT_DAYS)
    out = set()
    for w in block_workouts or []:
        day = str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]
        if since <= day < str(as_of)[:10]:
            out |= {str(x.get("template_id") or "").upper() for x in w.get("exercises") or [] if x.get("template_id")}
    return out


def for_apply(lib: dict[str, Any], position: Any, rows: Any, block_workouts: Any, target_date: str | None, approvals: Any) -> dict:
    """`selection_engine.apply`'s live policy. The gate evaluation is read beside the approval (`variant_rotation.for_session`
    read the ledger, so `approvals` is not None); an injected ledger reads neither and every gate stays locked."""
    from training import block_design_review

    as_of = target_date or (position or {}).get("date")
    read = approvals is not None
    gate_eval = block_design_review.load_gate_eval_failsoft(str(as_of or "")) if read else {"state": "not_read", "row": None}
    return build_policy(lib, position=position, rows=rows, block_workouts=block_workouts, as_of=as_of, gate_eval=gate_eval)


def summary(policy: dict[str, Any]) -> dict[str, Any]:
    """The live policy's fields on the selection record (no rows, no counts): `live_policy` and the live `gates_source`."""
    return {"live_policy": _summary(policy), "gates_source": LIVE_GATES_SOURCE}


def _summary(policy: dict[str, Any]) -> dict[str, Any]:
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
