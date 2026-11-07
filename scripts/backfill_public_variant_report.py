#!/usr/bin/env python3
"""scripts/backfill_public_variant_report.py — the manifest's evidence sections for ``backfill_public_variant`` (owner
rulings 2026-11-05/06): the reason for every change, the habit_pct impact, the historical invariance test (with its
mutation control), the evidence that public habit data moves Mind as it should, and the correction ledger. Pure over
the snapshot the CLI loaded — reads nothing, writes nothing.
"""

from __future__ import annotations

import copy
import json
from typing import Optional

import backfill_public_variant as B
from health import character_public, habit_pct_public

PRIVATE_MIND = ("journal_consistency", "state_of_mind_valence", "values_alignment", "stress_management")
LEDGER_VERSION = "public-variant-correction-ledger-v1"

REASONS = {
    "private_mind_components_removed": "Mind's private components (journal consistency, journal-coded values, How We Feel / State of "
    "Mind, check-in stress) are out of the public sum and coverage",
    "habit_scores_restored_by_order_fix": "the day's habit scores, which the old compute order never saw, now score Mind's habit "
    "components (reconstructed from the stored habit_scores record)",
    "mind_unavailable_insufficient_public_data": "no public-eligible Mind measurement: Mind is served as unavailable, not 0.0, "
    "and leaves the composite",
    "relationships_journal_xp_removed": "Relationships is computed only from the journal: no public reading, no XP",
    "consistency_recomputed_from_public_pillars": "Consistency's cross-pillar variance, streak and weekend/weekday ratio read the "
    "public pillars",
    "carried_state_chain": "levels, XP, debt and streaks carried forward from earlier public days",
    "day_grade_journal_component_removed": "the journal component is out of the day grade; the mean renormalises",
    "day_grade_tier_weighted_habits_held_out": "a tier-weighted (pre-core-set) day's habit share counted the journal habits and "
    "is held out of the public grade",
}


def _mind_comps(rec: dict) -> dict:
    return ((rec.get("pillar_mind") or {}).get("components")) or {}


def character_reasons(m1: dict, pub: Optional[dict], order_info: Optional[dict], changed: bool) -> list:
    """The reason codes (``REASONS``) behind a date's public change."""
    pub = pub or {}
    out = []
    comps = _mind_comps(m1)
    if any(
        isinstance(comps.get(n), dict)
        and comps[n].get("score") is not None
        and not comps[n].get("held_out")
        or (n == "journal_consistency" and isinstance(comps.get(n), dict))
        for n in PRIVATE_MIND
    ):
        out.append("private_mind_components_removed")
    if (order_info or {}).get("habit_scores_present") and (comps.get("t0_habit_compliance") or {}).get("absent"):
        out.append("habit_scores_restored_by_order_fix")
    if (pub.get("pillar_mind") or {}).get("not_instrumented"):
        out.append("mind_unavailable_insufficient_public_data")
    rel = m1.get("pillar_relationships") or {}
    if not rel.get("not_instrumented") or float(rel.get("xp_total") or 0) > 0:
        out.append("relationships_journal_xp_removed")
    if (m1.get("pillar_consistency") or {}).get("raw_score") != (pub.get("pillar_consistency") or {}).get("raw_score"):
        out.append("consistency_recomputed_from_public_pillars")
    if changed:
        out.append("carried_state_chain")
    return out


def grade_reasons(item: dict, habits: dict) -> list:
    out = []
    if item.get("component_journal") is not None:
        out.append("day_grade_journal_component_removed")
    if habits.get("policy") == "hold_out" and habits.get("stored") is not None:
        out.append("day_grade_tier_weighted_habits_held_out")
    return out


def habit_pct_rows(habitify: dict, registry: dict) -> list:
    """Per Habitify day: the habit_pct method 1 published vs the public method, and how many habits each counted."""
    from common import activity_publication as A

    rows = []
    for d, rec in sorted(habitify.items()):
        habits = rec.get("habits") if isinstance(rec.get("habits"), dict) else {}
        sts = rec.get("habit_statuses") if isinstance(rec.get("habit_statuses"), dict) else {}
        fam = [A.habit_family(n, sts.get(n), registry.get(n)) for n in habits]
        rows.append(
            {
                "date": d,
                "habit_pct": [B._r(habit_pct_public.method1_habit_pct(rec)), B._r(habit_pct_public.public_habit_pct(rec, registry))],
                "habits_counted": [len(habits), sum(1 for n in habits if A.habit_is_public(n, sts.get(n), registry.get(n)))],
                "excluded_private": sum(1 for f in fam if f in ("journal_presence", A.OWNER_DECLARED_PRIVATE)),
                "excluded_unclassified": sum(1 for f in fam if f == A.UNCLASSIFIED_HABIT),
            }
        )
    return rows


def _blocks(replayed: dict) -> str:
    return json.dumps(
        {d: {k: v for k, v in (r["public"] or {}).items() if k != "computed_at"} for d, r in replayed.items()}, sort_keys=True, default=str
    )


def _vary_private(sheets: dict, high: bool) -> dict:
    """Every stored record with ONLY its private inputs replaced: Mind's private components, the Relationships pillar."""
    out = {}
    for d, rec in sheets.items():
        r = copy.deepcopy(rec)
        comps = _mind_comps(r)
        for n in PRIVATE_MIND:
            comps[n] = {"score": 100.0 if high else None, "weight": 0.1}
        rel = r.get("pillar_relationships") or {}
        rel.update({"raw_score": 90.0 if high else 50.0, "not_instrumented": not high, "xp_total": 9.0 if high else 0.0})
        r["pillar_relationships"] = rel
        out[d] = r
    return out


def _vary_presence(engagement: dict, journal_quiet: bool) -> dict:
    out = {}
    for d, rec in engagement.items():
        r = copy.deepcopy(rec)
        q = [c for c in (r.get("channels_quiet") or []) if c != "journal"]
        r["channels_quiet"] = q + (["journal"] if journal_quiet else [])
        out[d] = r
    return out


def historical_invariance(snap: dict, config: dict, run_ts: str) -> dict:
    """The REAL history replayed with every private input set high, then absent: the public variants must be
    byte-identical (and the day grades); the mutation control (a method that kept the private components) must not be."""
    hs = snap["habit_scores"]
    hi = B.replay_character(_vary_private(snap["sheets"], True), _vary_presence(snap["engagement"], True), hs, config, run_ts)
    lo = B.replay_character(_vary_private(snap["sheets"], False), _vary_presence(snap["engagement"], False), hs, config, run_ts)
    base = B.replay_character(snap["sheets"], snap["engagement"], hs, config, run_ts)
    grade_hi = {
        d: B.replay_day_grade(dict(i, component_journal=100), None, None, snap["profile"], run_ts)["public"]
        for d, i in snap["grades"].items()
    }
    grade_lo = {
        d: B.replay_day_grade(dict(i, component_journal=0), None, None, snap["profile"], run_ts)["public"]
        for d, i in snap["grades"].items()
    }
    strip = lambda g: json.dumps(
        {d: {k: v for k, v in b.items() if k != "computed_at"} for d, b in g.items()}, sort_keys=True, default=str
    )  # noqa: E731
    keep = character_public.mind_component_is_public
    try:
        character_public.mind_component_is_public = lambda n: n in character_public.MIND_COMPONENT_SOURCES
        m_hi = B.replay_character(_vary_private(snap["sheets"], True), snap["engagement"], hs, config, run_ts)
        m_lo = B.replay_character(_vary_private(snap["sheets"], False), snap["engagement"], hs, config, run_ts)
    finally:
        character_public.mind_component_is_public = keep
    return {
        "dates": len(base),
        "private_inputs_high_vs_absent_identical": _blocks(hi) == _blocks(lo),
        "private_inputs_high_vs_stored_identical": _blocks(hi) == _blocks(base),
        "day_grade_journal_100_vs_0_identical": strip(grade_hi) == strip(grade_lo),
        "mutation_control_kept_private_components_differs": _blocks(m_hi) != _blocks(m_lo),
    }


def habit_evidence(snap: dict, char: dict, config: dict) -> list:
    """For each date whose fixed-order habit scores reached Mind: the inputs, the public Mind raw, the value the
    published formula gives from those inputs, and the Mind raw with the core share 20 points higher."""
    cfg = character_public.public_config(config)
    out = []
    for d, r in sorted(char.items()):
        info = r.get("order_fix") or {}
        if not info.get("habit_scores_present") or not r.get("public"):
            continue
        m1_in, method, _vice, _info = B.order_fixed_inputs(snap["sheets"][d], snap["habit_scores"], config)
        det = _mind_comps(m1_in)
        raw, pdet = character_public.public_mind(det, method, cfg)
        bumped = copy.deepcopy(det)
        for n in ("t0_habit_compliance", "t1_habit_compliance"):
            if isinstance(bumped.get(n), dict) and bumped[n].get("score") is not None and not bumped[n].get("absent"):
                bumped[n] = dict(bumped[n], score=min(100.0, float(bumped[n]["score"]) + 20))
        raw_up = character_public.public_mind(bumped, method, cfg)[0]
        comps = cfg["pillars"]["mind"]["components"]
        used = {n: v["score"] for n, v in pdet.items() if not n.startswith("_") and isinstance(v, dict) and v.get("score") is not None}
        w = sum(comps[n]["weight"] for n in used)
        expected = round(sum(used[n] * comps[n]["weight"] for n in used) / w, 1) if w else None
        out.append(
            {
                "date": d,
                "scoring_method": method,
                "restored": info.get("restored"),
                "public_mind_raw_served": B._r((r["public"].get("pillar_mind") or {}).get("raw_score")),
                "public_mind_raw_recomputed": B._r(raw),
                "formula_unblended_from_inputs": expected,
                "unblended_served": B._r(pdet.get("_raw_unblended")),
                "mind_raw_with_core_share_plus_20": B._r(raw_up),
                "unavailable": bool(pdet.get("_not_instrumented")),
            }
        )
    return out


def ledger_rows(c_rows: list, g_rows: list, h_rows: list, snap: dict, run_ts: str) -> list:
    """The correction ledger: one row per changed published value — method 1 (kept privately, with its original
    computed_at), the public value, the method, the reasons, the recomputation instant. The apply run fills `export`."""
    out = []
    fields = ("mind_raw", "mind_level", "composite", "character_xp", "character_level", "consistency_level")
    for r in c_rows:
        rec = snap["sheets"][r["date"]]
        for f in fields:
            if r[f][0] != r[f][1]:
                out.append(
                    _ledger("character_sheet", r["date"], f, r[f], rec.get("computed_at"), "character-public-v1", r["reasons"], run_ts)
                )
    for r in g_rows:
        rec = snap["grades"][r["date"]]
        for f in ("day_grade", "letter"):
            if r[f][0] != r[f][1]:
                out.append(_ledger("day_grade", r["date"], f, r[f], rec.get("computed_at"), "day-grade-public-v1", r["reasons"], run_ts))
    for r in h_rows:
        if r["habit_pct"][0] != r["habit_pct"][1]:
            out.append(
                _ledger(
                    "habitify(derived)",
                    r["date"],
                    "habit_pct",
                    r["habit_pct"],
                    None,
                    habit_pct_public.METHOD_VERSION,
                    ["habit_pct_public_habits_only"],
                    run_ts,
                )
            )
    return out


def _ledger(partition, d, field, pair, m1_at, method, reasons, run_ts) -> dict:
    return {
        "ledger_version": LEDGER_VERSION,
        "partition": partition,
        "date": d,
        "field": field,
        "method1_value": pair[0],
        "method1_computed_at": m1_at,
        "public_value": pair[1],
        "public_method_version": method,
        "reasons": reasons,
        "recomputed_at": run_ts,
        "export": None,
    }
