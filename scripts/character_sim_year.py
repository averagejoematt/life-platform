#!/usr/bin/env python3
"""
char_sim_year.py — YEAR-SCALE defensibility simulation of the character engine.

Drives the REAL lambdas/character_engine.py orchestrator (compute_character_sheet)
day by day for 420+ days across 6 scenarios, by monkeypatching PILLAR_COMPUTERS /
compute_consistency_raw to return scripted (raw_score, details) pairs. Everything
downstream — EMA, cross-pillar effects, neglect decay, level/tier/streak gates,
XP/debt, mood — is the production code path, untouched.

No AWS calls. Local config config/character_sheet.json.

Scenarios (420 days unless noted):
  a   steady-good        raw ~75 all pillars (production-real: relationships frozen)
  a2  steady-excellent   raw ~90 (time-to-Elite question)
  a3  steady-excellent   raw ~90 + relationships instrumented (isolate the 0.07 cap)
  b   oscillation        2 good weeks (~75) / 1 bad week (~45)
  c   dark stretch       ~75 to day 89, 30 dark days (presence=dark, absence math),
                         recovery ~75 from day 120
  d   2-cycle cold start 180 days ~72, full wipe, 240 more days ~72 (same RNG)
  e   slow improver      raw 45 -> 70 linear

"Production-real" = the relationships pillar has no data source (#747): raw is the
50.0 not-instrumented placeholder at coverage 0.0 (coverage-hold, level frozen at 1).
Dark-day (raw, coverage) pairs are derived from the engine's own ADR-104 absence
math (behavioral components score 0 at full weight, measured components drop out,
confidence blend toward 50) using each pillar's behavioral weight share.
"""
import copy
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path("/Users/matthewwalker/Documents/Claude/life-platform")
sys.path.insert(0, str(REPO / "lambdas"))

import character_engine as ce  # noqa: E402

CONFIG = json.loads((REPO / "config" / "character_sheet.json").read_text())
PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
GENESIS = date(2026, 7, 12)

# ---------------------------------------------------------------------------
# Monkeypatch: scripted pillar computers reading (raw, cov) from data["_script"]
# ---------------------------------------------------------------------------


def _scripted(pillar):
    def fn(data, config):
        raw, cov = data["_script"][pillar]
        details = {
            "_confidence": min(1.0, cov / 0.80) if cov > 0 else 0.0,
            "_data_coverage": cov,
            "_absent_behaviors": [],
            "_not_instrumented": cov == 0.0,
        }
        return raw, details

    return fn


ce.PILLAR_COMPUTERS = {p: _scripted(p) for p in PILLARS if p != "consistency"}
_cons = _scripted("consistency")
ce.compute_consistency_raw = lambda data, config, other: _cons(data, config)

# ---------------------------------------------------------------------------
# Dark-day absence math (mirrors _weighted_pillar_score with ADR-104 semantics)
# behavioral comps -> 0 at full weight; measured comps that still stream keep a
# mediocre score; the rest drop out. Derived per pillar from the live config.
# ---------------------------------------------------------------------------
# Which measured components keep streaming during a logging dark stretch
# (wearables stay on the wrist): sleep = all wearable, metabolic = cgm/rhr,
# movement/nutrition/mind lose the manual half.
DARK_MEASURED_ALIVE = {
    "sleep": {"duration_vs_target": 60, "efficiency": 65, "deep_sleep_pct": 55, "rem_pct": 55, "onset_consistency": 50},
    "movement": {"daily_steps": 30},  # phone still counts some steps
    "nutrition": {},  # no weigh-ins, no logging
    "metabolic": {"cgm_glucose_control": 55, "resting_heart_rate": 60},
    "mind": {"stress_management": 50},  # whoop recovery still streams
    "relationships": {},
    "consistency": {"data_completeness": 30},
}


def dark_day(pillar):
    comps = CONFIG["pillars"][pillar]["components"]
    wsum = tsum = 0.0
    maxw = 0.0
    for name, cfg in comps.items():
        w = cfg.get("weight", 0)
        maxw += w
        if cfg.get("behavioral"):
            wsum += 0.0 * w
            tsum += w
        elif name in DARK_MEASURED_ALIVE.get(pillar, {}):
            wsum += DARK_MEASURED_ALIVE[pillar][name] * w
            tsum += w
    if tsum == 0:
        return 50.0, 0.0  # not instrumented that day
    raw = wsum / tsum
    cov = tsum / maxw
    conf = min(1.0, cov / 0.80)
    return round(raw * conf + 50.0 * (1 - conf), 1), round(cov, 3)


DARK = {p: dark_day(p) for p in PILLARS}

# Per-pillar personality offsets for good days
OFFSET = {"sleep": 3, "movement": -2, "nutrition": 0, "metabolic": 1, "mind": -3, "consistency": 2}


def good_day(rng, base, rel_instrumented=False):
    """One engaged day: raw = base + offset + N(0,4), coverage 0.9."""
    script = {}
    for p in PILLARS:
        if p == "relationships" and not rel_instrumented:
            script[p] = (50.0, 0.0)  # not instrumented (#747)
            continue
        raw = max(0.0, min(100.0, base + OFFSET.get(p, 0) + rng.gauss(0, 4)))
        script[p] = (round(raw, 1), 0.9)
    return script


# ---------------------------------------------------------------------------
# Simulation driver
# ---------------------------------------------------------------------------


def run(days_fn, n_days, genesis=GENESIS, state=None):
    """days_fn(i, rng) -> (script, engagement). Returns list of daily records."""
    cfg = copy.deepcopy(CONFIG)
    cfg["experiment_start"] = genesis.isoformat()
    prev, histories = (None, {p: [] for p in PILLARS}) if state is None else state
    out = []
    for i in range(n_days):
        script, engagement = days_fn(i)
        data = {"date": (genesis + timedelta(days=i)).isoformat(), "_script": script, "engagement_state": engagement}
        rec = ce.compute_character_sheet(data, prev, histories, cfg)
        for p in PILLARS:
            histories[p].append(rec[f"pillar_{p}"]["raw_score"])
        out.append(rec)
        prev = rec
    return out


ENGAGED = {"presence_class": "present", "gap_days": 0, "planned_pause": False}


def scen_steady(base, rel_instrumented=False, seed=1):
    rng = random.Random(seed)
    return lambda i: (good_day(rng, base, rel_instrumented), dict(ENGAGED))


def scen_oscillation(seed=2):
    rng = random.Random(seed)

    def fn(i):
        base = 75 if (i % 21) < 14 else 45
        return good_day(rng, base), dict(ENGAGED)

    return fn


def scen_dark(seed=3):
    rng = random.Random(seed)

    def fn(i):
        if 90 <= i < 120:
            gap = i - 89
            eng = {"presence_class": "dark", "gap_days": gap, "planned_pause": False}
            return dict(DARK), eng
        return good_day(rng, 75), dict(ENGAGED)

    return fn


def scen_slow(seed=5):
    rng = random.Random(seed)
    return lambda i: (good_day(rng, 45 + 25 * i / 419), dict(ENGAGED))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def analyze(name, recs, note=""):
    levels = [r["character_level"] for r in recs]
    print(f"\n{'=' * 78}\nSCENARIO {name}  ({len(recs)} days)  {note}")
    milestones = {}
    for m in (10, 20, 30, 40, 50, 60, 70, 75, 81, 90):
        d = next((i + 1 for i, lv in enumerate(levels) if lv >= m), None)
        if d:
            milestones[m] = d
    print("  char-level milestones (level: day):", milestones or "none past 10")
    tiers = {}
    for r in recs:
        tiers[r["character_tier"]] = tiers.get(r["character_tier"], 0) + 1
    print("  tier dwell (days):", tiers)
    for day in (30, 90, 180, 365, 420):
        if day <= len(recs):
            r = recs[day - 1]
            plv = {p[:4]: r[f"pillar_{p}"]["level"] for p in PILLARS}
            print(
                f"  day {day:>3}: char L{r['character_level']:>2} ({r['character_tier'][:4]})  "
                f"xp {r['character_xp']:>5.0f}  debt {r['character_xp_debt']:>3.0f}  "
                f"mood {r['character_mood']:<8}  pillars {plv}"
            )
    ups = downs = flip = 0
    per_pillar_events = {p: [] for p in PILLARS}
    for i, r in enumerate(recs):
        for ev in r["level_events"]:
            if ev["type"] == "level_up":
                ups += 1
                per_pillar_events[ev["pillar"]].append((i, +1))
            elif ev["type"] == "level_down":
                downs += 1
                per_pillar_events[ev["pillar"]].append((i, -1))
    for p, evs in per_pillar_events.items():
        for (d1, s1), (d2, s2) in zip(evs, evs[1:]):
            if s1 != s2 and d2 - d1 <= 21:
                flip += 1
    moods = {}
    for r in recs:
        moods[r["character_mood"]] = moods.get(r["character_mood"], 0) + 1
    print(f"  level events: {ups} ups / {downs} downs / {flip} direction flips within 21d")
    print("  mood days:", moods)
    # XP trajectory + the modulo buffer
    for day in (100, 200, 300, 400):
        if day <= len(recs):
            r = recs[day - 1]
            bufs = {p[:4]: r[f"pillar_{p}"]["xp_buffer"] for p in PILLARS}
            debts = {p[:4]: r[f"pillar_{p}"]["xp_debt"] for p in PILLARS if r[f"pillar_{p}"]["xp_debt"]}
            print(f"  day {day}: total_xp {r['character_xp']:>5.0f}  buffers {bufs}  debts {debts or '{}'}")
    return levels


def main():
    print(f"engine v{ce.ENGINE_VERSION} | config v{CONFIG['_meta']['version']} | genesis {GENESIS}")
    print("dark-day (raw, coverage) derived from live config absence math:")
    for p in PILLARS:
        print(f"   {p:<14} {DARK[p]}")

    # (a) steady-good 75 — production-real
    recs_a = run(scen_steady(75), 420)
    analyze("a: steady-good raw~75 (relationships frozen, production-real)", recs_a)

    # (a2) steady-excellent 90 — production-real
    recs_a2 = run(scen_steady(90, seed=11), 420)
    analyze("a2: steady-EXCELLENT raw~90 (production-real) — time to Elite?", recs_a2)

    # (a3) excellent + relationships instrumented
    recs_a3 = run(scen_steady(90, rel_instrumented=True, seed=11), 420)
    analyze("a3: steady-EXCELLENT raw~90 + relationships instrumented", recs_a3)

    # (b) oscillation
    recs_b = run(scen_oscillation(), 420)
    analyze("b: oscillation 2wk good(75) / 1wk bad(45)", recs_b)

    # (c) dark stretch
    recs_c = run(scen_dark(), 420)
    lv = [r["character_level"] for r in recs_c]
    analyze("c: good 75 -> 30 DARK days at day 90 -> recovery", recs_c)
    pre = lv[88]
    dark_min = min(lv[89:150])
    rec_day = next((i + 1 for i in range(119, len(lv)) if lv[i] >= pre), None)
    print(
        f"  >> pre-dark level (day 89): {pre} | min during/after dark: {dark_min} "
        f"(drop {pre - dark_min}) | day recovered to pre-dark: {rec_day}"
    )
    # daily zoom of the dark window
    print("  >> dark-window zoom (day: char level, mood, movement lvl/score, mind lvl):")
    for i in range(85, 135, 5):
        r = recs_c[i]
        pm, pmind = r["pillar_movement"], r["pillar_mind"]
        nd = r.get("neglect_decay")
        print(
            f"     d{i + 1:>3}: L{r['character_level']:>2} {r['character_mood']:<8} "
            f"mv L{pm['level']:>2}/{pm['level_score']:>5.1f} mind L{pmind['level']:>2} "
            f"debt {r['character_xp_debt']:>3.0f} decay_mult {nd['multiplier'] if nd else '—'}"
        )

    # (d) two-cycle cold start: 180 days, wipe, 240 days — same seed
    recs_d1 = run(scen_steady(72, seed=42), 180)
    recs_d2 = run(scen_steady(72, seed=42), 240, genesis=GENESIS + timedelta(days=180))
    analyze("d/cycle1: 180 days raw~72 then WIPE", recs_d1)
    analyze("d/cycle2: fresh 240 days raw~72 (same RNG)", recs_d2)
    l1 = [r["character_level"] for r in recs_d1]
    l2 = [r["character_level"] for r in recs_d2][:180]
    same = l1 == l2
    print(f"  >> cycle2 day-aligned trajectory identical to cycle1: {same} " f"(max abs diff {max(abs(a - b) for a, b in zip(l1, l2))})")

    # (e) slow improver 45 -> 70
    recs_e = run(scen_slow(), 420)
    analyze("e: slow improver raw 45 -> 70 linear", recs_e)

    # focused probe: XP mechanics on a NOT-INSTRUMENTED pillar (relationships)
    print(f"\n{'=' * 78}\nPROBE: relationships (not instrumented, coverage 0.0) XP over scenario (a)")
    for day in (14, 30, 60, 120, 400):
        r = recs_a[day - 1]
        pr = r["pillar_relationships"]
        print(
            f"  day {day:>3}: raw {pr['raw_score']} cov {pr['data_coverage']} hold {pr['coverage_hold']} "
            f"level {pr['level']} xp {pr['xp_total']} debt {pr['xp_debt']} xp_earned {pr['xp_earned']}"
        )

    # focused probe: WHY metabolic freezes at L1 in (a) — the #913 up-gate compares
    # the day's raw against the cross-pillar-BOOSTED target (character_engine.py:1099
    # vs :1425 — level eval receives adjusted_level_scores). Training Boost (+5%) +
    # Synergy (+8%) + Alignment (+3%) = x1.161: target ~89 while raw days are ~76,
    # so day_supports_up is permanently False and streak_above never leaves 0.
    print(f"\n{'=' * 78}\nPROBE: metabolic up-gate vs boosted target (scenario a, days 21-60)")
    for i in (20, 30, 40, 50, 59):
        r = recs_a[i]
        pm = r["pillar_metabolic"]
        target = round(pm["level_score"])
        print(
            f"  d{i + 1:>3}: raw {pm['raw_score']:>5.1f}  adj_level_score {pm['level_score']:>5.1f} "
            f"(target {target})  raw>=target {round(pm['raw_score']) >= target}  "
            f"level {pm['level']}  streak_above {pm['streak_above']}  "
            f"effects {[e['name'] for e in r['active_effects']]}"
        )
    raws_meta = [rec["pillar_metabolic"]["raw_score"] for rec in recs_a[:60]]
    ema_unadj = ce.compute_ema_level_score(raws_meta, CONFIG, "metabolic")
    print(
        f"  day 60 unadjusted EMA {ema_unadj} vs adjusted {recs_a[59]['pillar_metabolic']['level_score']}"
        f" (boost x{recs_a[59]['pillar_metabolic']['level_score'] / ema_unadj:.3f})"
    )

    # focused probe: buffer-gate behavior entering the dark stretch (scenario c)
    print("\nPROBE: XP-buffer gate arbitrariness — movement pillar, days 88-125 (scenario c)")
    for i in range(87, 125, 2):
        r = recs_c[i]
        pm = r["pillar_movement"]
        print(
            f"  d{i + 1:>3}: lvl {pm['level']:>2} xp {pm['xp_total']:>4.0f} buffer {pm['xp_buffer']:>3.0f} "
            f"sb {pm['streak_below']:>2} debt {pm['xp_debt']:>3.0f}"
        )


if __name__ == "__main__":
    main()
