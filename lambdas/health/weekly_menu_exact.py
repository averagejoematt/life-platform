"""The weekly menu's exact day search (#5103 search quality), split out of `health.weekly_menu` for the module-size
ceiling (#1665). When no rotation fits a day, `_exact_day` finds the day's one best anchor set by branch-and-bound
over every core assignment and side serving count. The shared primitives (the macro vector, the cost, the Atwater
exchange rate) live here so `weekly_menu` imports them one way, with no import cycle."""

from __future__ import annotations

import bisect
import itertools
from typing import Any, Mapping, Optional, Sequence

from health import travel_food

MACROS = travel_food.MACROS  # kcal, protein_g, carb_g, fat_g, fibre_g
GRAMS = ("protein_g", "carb_g", "fat_g", "fibre_g")
# The exchange rate between a floor gram short and a calorie: the Atwater factors (fibre at the carbohydrate rate, as
# the travel kit's search prices it). A physical constant of the search, not a target.
ATWATER = {"protein_g": 4.0, "carb_g": 4.0, "fat_g": 9.0, "fibre_g": 4.0}
# Bound on one exact search, in branch-and-bound nodes; `weekly_menu.EXACT_NODE_BUDGET` is the caller's per-day value.
EXACT_NODE_BUDGET = 60_000
Counts = dict[str, int]


def _cost(tot: Mapping[str, float], t: Mapping[str, Any]) -> tuple[float, float]:
    """(the miss, the distance): the floor shortfall at the Atwater rate plus the kcal outside the day's band — what
    makes a day unfit — first; the distance from the day's kcal only breaks ties between days that miss equally."""
    gap = sum(ATWATER[m] * max(0.0, float(f) - tot[m]) for m, f in t["floors_g"].items())
    dist = abs(tot["kcal"] - float(t["kcal"]))
    return round(gap + max(0.0, dist - float(t["tolerance_kcal"])), 3), round(dist, 3)


def _vec(counts: Mapping[str, int], by_id: Mapping[str, Mapping[str, Any]]) -> tuple[float, ...]:
    return tuple(sum(float(by_id[k][m]) * n for k, n in counts.items()) for m in MACROS)


def _cost_vec(v: Sequence[float], t: Mapping[str, Any]) -> tuple[float, float]:
    return _cost(dict(zip(MACROS, v)), t)


def _merge(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, n in b.items():
        out[k] = out.get(k, 0) + n
    return out


def _knapsack_curves(items: Sequence[tuple[float, tuple[float, ...], int]]) -> list[tuple[list[float], list[float]]]:
    """For each floor gram (protein, carbohydrate, fat, fibre, in GRAMS order), the most of it `items` can add for a
    given added kcal when servings may be fractional: the fractional-knapsack curve (cumulative kcal, cumulative grams),
    the items taken densest-first. Concave and non-decreasing, so it bounds what ANY whole-serving choice of the items
    adds at that kcal."""
    out = []
    for gi in range(1, len(MACROS)):
        order = sorted(items, key=lambda it: (-(it[1][gi] / it[1][0]), it[1][0]))
        ks, gs = [0.0], [0.0]
        for kcal, vec, cap in order:
            ks.append(ks[-1] + vec[0] * cap)
            gs.append(gs[-1] + vec[gi] * cap)
        out.append((ks, gs))
    return out


def _curve_at(curve: tuple[list[float], list[float]], k: float) -> float:
    ks, gs = curve
    if k >= ks[-1]:
        return gs[-1]
    i = bisect.bisect_right(ks, k)
    k0, k1 = ks[i - 1], ks[i]
    return gs[i - 1] + (gs[i] - gs[i - 1]) * ((k - k0) / (k1 - k0) if k1 > k0 else 0.0)


def _curve_inverse(curve: tuple[list[float], list[float]], g: float) -> Optional[float]:
    """The least added kcal at which the curve reaches `g` grams (None when it never does)."""
    ks, gs = curve
    if g <= 0:
        return 0.0
    if g > gs[-1]:
        return None
    i = bisect.bisect_left(gs, g)
    g0, g1 = gs[i - 1], gs[i]
    return ks[i - 1] + (ks[i] - ks[i - 1]) * ((g - g0) / (g1 - g0) if g1 > g0 else 0.0)


def _miss_bound(
    cur: Sequence[float], curves: Sequence[tuple[list[float], list[float]]], kinks: Sequence[float], t: Mapping[str, Any]
) -> float:
    """A lower bound on the miss (`_cost`'s first term) of every completion of a partial day: the day's totals so far
    are `cur`, and the foods still to choose can add at most `curves[g](K)` grams of each floor gram at added kcal K.
    The bound is the least, over K, of h(K) = the floor shortfall at those grams plus the kcal outside the band at
    cur + K. Valid because a real completion with added kcal K adds no more of any gram than its curve allows there.
    h is convex and piecewise linear (each curve is concave), so its least value sits at a kink: the curves' own
    breakpoints (`kinks`, sorted), the band's edges and each floor's crossing. The least over `kinks` is found by
    bisection (a convex sequence), and the true least lies within one breakpoint of it — where only the band edges and
    the crossings can add a kink — so those few are evaluated too."""
    lo, hi = t["band"]
    floors = [float(t["floors_g"].get(m) or 0.0) - cur[gi + 1] for gi, m in enumerate(GRAMS)]
    weights = [ATWATER[m] for m in GRAMS]
    top = kinks[-1] if kinks else 0.0

    def h(k: float) -> float:
        gap = sum(w * max(0.0, need - _curve_at(cv, k)) for cv, w, need in zip(curves, weights, floors) if need > 0)
        kc = cur[0] + k
        return gap + max(0.0, kc - hi) + max(0.0, lo - kc)

    extra = [edge for edge in (lo - cur[0], hi - cur[0]) if 0.0 < edge < top]
    for gi, need in enumerate(floors):
        if need > 0:
            k = _curve_inverse(curves[gi], need)
            if k is not None and 0.0 < k < top:
                extra.append(k)
    if not kinks:
        return h(0.0)
    left, right = 0, len(kinks) - 1
    while left < right:
        mid = (left + right) // 2
        if h(kinks[mid]) <= h(kinks[mid + 1]):
            right = mid
        else:
            left = mid + 1
    return min([h(kinks[left]), *(h(k) for k in extra)])


def _decompose(counts: Mapping[str, int], pools: Sequence[Sequence[Counts]]) -> Optional[list[Counts]]:
    """One core per feeding (feeding i's from `pools[i]`, in pool order) whose servings all sit inside `counts`, or
    None when no assignment does. The first assignment in pool order is taken, so the split is deterministic."""
    failed: set[tuple[int, tuple[tuple[str, int], ...]]] = set()

    def walk(slot: int, left: dict[str, int]) -> Optional[list[Counts]]:
        if slot == len(pools):
            return []
        memo = (slot, tuple(sorted((k, n) for k, n in left.items() if n)))
        if memo in failed:
            return None
        for core in pools[slot]:
            if all(left.get(k, 0) >= n for k, n in core.items()):
                rest = walk(slot + 1, {k: n - core.get(k, 0) for k, n in left.items()})
                if rest is not None:
                    return [core, *rest]
        failed.add(memo)
        return None

    return walk(0, dict(counts))


def _core_sets(pools: Sequence[Sequence[Counts]], caps: Mapping[str, int]) -> list[tuple[Counts, ...]]:
    """Every way to give each feeding one core from its pool inside the per-day caps, one entry per distinct serving
    total (feedings that share a pool take its cores as a multiset: the order of two equal feedings is not a choice),
    in a fixed order (pool order), so the search below walks them the same way every time."""
    groups: dict[int, list[int]] = {}
    for slot, pool in enumerate(pools):
        groups.setdefault(id(pool), []).append(slot)
    plans = [(slots, pools[slots[0]]) for slots in groups.values()]
    choices = [list(itertools.combinations_with_replacement(range(len(pool)), len(slots))) for slots, pool in plans]
    out: list[tuple[Counts, ...]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    for pick in itertools.product(*choices):
        by_slot: dict[int, Counts] = {}
        for (slots, pool), idx in zip(plans, pick):
            for slot, ci in zip(slots, idx):
                by_slot[slot] = pool[ci]
        total: Counts = {}
        for c in by_slot.values():
            for k, n in c.items():
                total[k] = total.get(k, 0) + n
        if any(n > caps.get(k, 0) for k, n in total.items()):
            continue
        sig = tuple(sorted(total.items()))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(tuple(by_slot[slot] for slot in range(len(pools))))
    return out


def _exact_day(
    pools: Sequence[Sequence[Counts]],
    anchors: Sequence[Mapping[str, Any]],
    t: Mapping[str, Any],
    fixed_vec: Optional[Sequence[float]] = None,
    incumbent: Optional[Mapping[str, int]] = None,
    require: Optional[Mapping[str, int]] = None,
    budget: int = EXACT_NODE_BUDGET,
) -> tuple[Optional[tuple[list[Counts], Counts]], dict[str, Any]]:
    """The day's BEST set, exactly. Every assignment of one core per feeding (`_core_sets`) is taken in turn, and for
    each a branch-and-bound over every side serving count of every anchor (0 up to what its cap leaves) — together,
    every set the local search could ever reach. It minimises one total order (the miss, the distance, the servings,
    the counts in id order), so the answer is the one global optimum whatever the starting point, and the same input
    always gives the same set (split into cores by `_decompose`, so the split is a function of the set alone). A branch
    is cut only when no completion can beat the best set found: its miss bound (`_miss_bound`) is above the best miss,
    or the best fits and no completion can land nearer the day's kcal. The `incumbent` (the local search's set) seeds
    the bound. `require` names servings every set must hold (the day's pinned fatty fish: in a core or as a side).
    Returns ((cores, sides), stats) — None when no assignment fits the caps — with stats {nodes, core_sets,
    complete}: `complete` is False only when the `budget` of nodes ran out first (the best found so far is kept and the
    day says so)."""
    by_id = {a["id"]: a for a in anchors}
    ids = sorted(by_id)
    caps = {k: int(by_id[k]["cap"]) for k in ids}
    base = tuple(fixed_vec) if fixed_vec is not None else (0.0,) * len(MACROS)
    unit_of = {k: _vec({k: 1}, by_id) for k in ids}
    target = float(t["kcal"])
    stats: dict[str, Any] = {"nodes": 0, "core_sets": 0, "complete": True}

    def key(total: Mapping[str, int], vec: Sequence[float]) -> tuple[Any, ...]:
        return (*_cost_vec(vec, t), sum(total.values()), tuple(total.get(k, 0) for k in ids))

    best: list[Any] = [None, None]  # key, total counts
    need = {k: int(n) for k, n in (require or {}).items() if n}
    if incumbent is not None:
        inc = {k: int(n) for k, n in incumbent.items() if n}
        if all(inc.get(k, 0) >= n for k, n in need.items()) and _decompose(inc, pools) is not None:
            vec = tuple(b + sum(unit_of[k][i] * n for k, n in inc.items()) for i, b in enumerate(base))
            best[:] = [key(inc, vec), inc]

    def cut(cur: Sequence[float], miss_lb: float, reach: float) -> bool:
        """True when no completion of this branch can beat the best set found."""
        if best[0] is None:
            return False
        if miss_lb > best[0][0] + 1e-3:
            return True
        if best[0][0] == 0.0:  # the best fits: only a fit nearer the day's kcal can beat it
            lo_k, hi_k = cur[0], cur[0] + reach
            dist_lb = 0.0 if lo_k <= target <= hi_k else min(abs(lo_k - target), abs(hi_k - target))
            return dist_lb > best[0][1] + 1e-3
        return False

    def sides_search(core_total: Counts) -> None:
        must = {k: max(0, n - core_total.get(k, 0)) for k, n in need.items()}  # required servings no core holds
        if any(core_total.get(k, 0) + n > caps.get(k, 0) for k, n in must.items()):
            return
        core_total = _merge(core_total, {k: n for k, n in must.items() if n})
        left = {k: caps[k] - core_total.get(k, 0) for k in ids}
        # The biggest foods first: deciding them early shrinks what the rest can add, which tightens every bound.
        order = sorted((k for k in ids if left[k] > 0), key=lambda k: (-unit_of[k][0] * left[k], k))
        unit = [unit_of[k] for k in order]
        room = [left[k] for k in order]
        curves, kinks, reach = [], [], []
        for i in range(len(order) + 1):
            cv = _knapsack_curves([(unit[j][0], unit[j], room[j]) for j in range(i, len(order))])
            curves.append(cv)
            kinks.append(sorted({k for ks, _gs in cv for k in ks}))
            reach.append(sum(u[0] * r for u, r in zip(unit[i:], room[i:])))
        counts = [0] * len(order)
        start = tuple(b + sum(unit_of[k][i] * n for k, n in core_total.items()) for i, b in enumerate(base))

        def dfs(i: int, cur: tuple[float, ...]) -> None:
            stats["nodes"] += 1
            if stats["nodes"] > budget:
                stats["complete"] = False
                return
            if i == len(order):
                total = dict(core_total)
                for k, n in zip(order, counts):
                    if n:
                        total[k] = total.get(k, 0) + n
                kk = key(total, cur)
                if best[0] is None or kk < best[0]:
                    best[:] = [kk, total]
                return
            children = []
            for n in range(room[i] + 1):
                nxt = tuple(c + x * n for c, x in zip(cur, unit[i]))
                children.append((_miss_bound(nxt, curves[i + 1], kinks[i + 1], t), -n, nxt))
            children.sort()  # the most promising branch first: a good set is found early, so more is cut
            for miss_lb, neg_n, nxt in children:
                if cut(nxt, miss_lb, reach[i + 1]):
                    continue
                counts[i] = -neg_n
                dfs(i + 1, nxt)
                if not stats["complete"]:
                    return
            counts[i] = 0

        if not cut(start, _miss_bound(start, curves[0], kinks[0], t), reach[0]):
            dfs(0, start)

    # Every assignment's start is bounded first with what ALL the anchors could add (a looser bound than the one its own
    # side search uses, so it cuts nothing a tighter bound would keep), and the assignments are walked best bound
    # first: a good set early cuts the rest at a glance.
    every = _knapsack_curves([(unit_of[k][0], unit_of[k], caps[k]) for k in ids])
    every_kinks = sorted({k for ks, _gs in every for k in ks})
    every_reach = sum(unit_of[k][0] * caps[k] for k in ids)
    starts = []
    for pos, assignment in enumerate(_core_sets(pools, caps)):
        core_total: Counts = {}
        for c in assignment:
            for k, n in c.items():
                core_total[k] = core_total.get(k, 0) + n
        start = tuple(b + sum(unit_of[k][i] * n for k, n in core_total.items()) for i, b in enumerate(base))
        starts.append((_miss_bound(start, every, every_kinks, t), pos, start, core_total))
    starts.sort(key=lambda x: (x[0], x[1]))
    for miss_lb, _pos, start, core_total in starts:
        stats["core_sets"] += 1
        stats["nodes"] += 1
        if stats["nodes"] > budget:
            stats["complete"] = False
            break
        if cut(start, miss_lb, every_reach):
            continue
        sides_search(core_total)
        if not stats["complete"]:
            break
    if best[1] is None:
        return None, stats
    picked = _decompose(best[1], pools)
    if picked is None:  # unreachable: every set above holds an assignment; kept so a bug is named, never served
        return None, {**stats, "complete": False}
    sides = dict(best[1])
    for core in picked:  # one core at a time: two feedings' cores may share an anchor
        sides = _merge(sides, {k: -n for k, n in core.items()})
    return (list(picked), {k: n for k, n in sorted(sides.items()) if n}), stats
