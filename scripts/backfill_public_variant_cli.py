#!/usr/bin/env python3
"""scripts/backfill_public_variant_cli.py — the I/O half of ``backfill_public_variant.py`` (owner ruling 2026-11-05).

Loads the stored inputs (read-only), runs the replays, writes the manifest; ``--apply`` / ``--rollback`` are the only
writing paths, each refused unless passed explicitly. The pure replay logic is ``backfill_public_variant``.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import statistics
import sys
from datetime import date, datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_report as R  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402
from health import character_privacy, character_public  # noqa: E402

ROUTE_PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
VERBATIM_CHECK = ("raw_score", "level", "level_score", "xp_total", "xp_debt", "xp_buffer", "streak_above", "streak_below", "tier")


# ── reads ──────────────────────────────────────────────────────────────────────────────────


def query_all(table, pk: str, lo: str = "DATE#0000", hi: str = "DATE#9999") -> list:
    from boto3.dynamodb.conditions import Key

    out, kw = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(lo, hi)}
    while True:
        resp = table.query(**kw)
        out += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _dated(items: list, keep=lambda i: True) -> dict:
    return {B.day_of(i): decimals_to_float(i) for i in items if keep(i) and "#" not in str(i.get("sk", ""))[5:]}


def load_snapshot(table, to: str) -> dict:
    """Every stored input the replay reads, by date — the same partitions the two computes read."""
    hi = f"DATE#{to}~"
    genesis = B.EXPERIMENT_START_DATE
    snap = {
        "sheets": _dated(query_all(table, B.SHEET_PK, hi=hi), B.visible),
        "receipts": _dated(query_all(table, B.RECEIPT_PK, hi=hi), B.visible),
        "grades": {d: v for d, v in _dated(query_all(table, B.GRADE_PK, hi=hi)).items() if d >= genesis},
        "engagement": _dated(query_all(table, B.PFX + "engagement_state", hi=hi), B.visible),
        "habit_scores": _dated(query_all(table, B.PFX + "habit_scores", hi=hi)),
        "computed": _dated(query_all(table, B.PFX + "computed_metrics", f"DATE#{genesis}", hi)),
        "habitify": _dated(query_all(table, B.PFX + "habitify", f"DATE#{B.shift(genesis, -7)}", hi)),
        "strava": _dated(query_all(table, B.PFX + "strava", f"DATE#{genesis}", hi)),
    }
    snap["profile"] = decimals_to_float(table.get_item(Key={"pk": f"USER#{B.USER}", "sk": "PROFILE#v1"}).get("Item") or {})
    return snap


def load_config(table, s3) -> dict:
    """The effective engine config, built exactly as the compute builds it (S3 config + baselines + effect fit)."""
    from experiment import effect_fitter
    from health import character_engine, personal_baselines

    cfg = character_engine.load_character_config(s3, os.environ["S3_BUCKET"], force_refresh=True)
    cfg = personal_baselines.effective_character_config(cfg, table, B.PFX)
    effect_fitter.merge_fit_into_config(cfg, effect_fitter.load_latest_fit(table, B.USER))
    return cfg


# ── the replays over a snapshot ───────────────────────────────────────────────────────────


def habit_inputs(snap: dict, d: str) -> dict:
    """The scorer's inputs as the day's compute assembled them (window anchored at the morning after, #4637)."""
    anchor = B.shift(d, 1)
    days = [snap["habitify"][k] for k in sorted(snap["habitify"]) if B.shift(anchor, -7) <= k <= d]
    return {"date": d, "habitify": snap["habitify"].get(d), "habitify_7d": days, "strava": snap["strava"].get(d)}


def composite_method(snap: dict, d: str) -> Optional[str]:
    hm = ((snap["computed"].get(d) or {}).get("component_details") or {}).get("habits_mvp") or {}
    return hm.get("composite_method")


def run_replays(snap: dict, config: dict, run_ts: str) -> tuple:
    char = B.replay_character(snap["sheets"], snap["engagement"], snap["habit_scores"], config, run_ts)
    receipts = {}
    for d, r in char.items():
        if r.get("transitions") and d in snap["receipts"]:
            rec_like = {"date": d, B.PUBLIC: r["public"], "public_progression_transitions": r["transitions"]}
            receipts[d] = character_public.public_receipt(rec_like, config, snap["receipts"][d].get("input_rows"))
    grades = {}
    for d, item in sorted(snap["grades"].items()):
        cm = composite_method(snap, d)
        hi = habit_inputs(snap, d) if cm != "core_set" else None
        grades[d] = B.replay_day_grade(item, cm, hi, snap["profile"], run_ts, tier_era_policy=B.day_grade_public.TIER_WEIGHTED_HABITS)
    return char, receipts, grades


# ── the manifest ──────────────────────────────────────────────────────────────────────────


def served_view(stored: dict, public_block: Optional[dict]) -> Optional[dict]:
    """What /api/character serves from a record: the CURRENT serving (``public_block`` None: method 1 with the private
    pillar held, as main serves it before this change) or the new one (the public variant)."""
    if public_block is None:
        out = dict(stored)
        for name in character_privacy.PRIVATE_SOURCE_PILLARS:
            if f"pillar_{name}" in out:
                out[f"pillar_{name}"] = character_privacy.public_pillar(name, out[f"pillar_{name}"])
        return out
    return character_privacy.public_sheet(dict(stored, **{B.PUBLIC: public_block}))


def route_composite(view: Optional[dict]) -> Optional[float]:
    """/api/character's composite_score: the mean raw over the pillars that are not not-instrumented."""
    if not view:
        return None
    raws = [
        float((view.get(f"pillar_{p}") or {}).get("raw_score", 0))
        for p in ROUTE_PILLARS
        if not (view.get(f"pillar_{p}") or {}).get("not_instrumented")
    ]
    return round(sum(raws) / len(raws), 1) if raws else None


def _num(x):
    return None if x is None else round(float(x), 4)


def character_rows(snap: dict, char: dict) -> list:
    rows = []
    for d in sorted(char):
        m1 = snap["sheets"][d]
        pub = char[d]["public"]
        cur, new = served_view(m1, None), served_view(m1, pub) if pub else None
        unchanged = all(
            (m1.get(f"pillar_{p}") or {}).get(f) == ((pub or {}).get(f"pillar_{p}") or {}).get(f)
            for p in character_public.VERBATIM_PILLARS
            for f in VERBATIM_CHECK
        )
        mp, pp = m1.get("pillar_mind") or {}, (pub or {}).get("pillar_mind") or {}
        rows.append(
            {
                "date": d,
                "mind_raw": [_num(mp.get("raw_score")), _num(pp.get("raw_score"))],
                "mind_level": [_num(mp.get("level")), _num(pp.get("level"))],
                "mind_level_score": [_num(mp.get("level_score")), _num(pp.get("level_score"))],
                "mind_data_coverage": [_num(mp.get("data_coverage")), _num(pp.get("data_coverage"))],
                "mind_xp_total": [_num(mp.get("xp_total")), _num(pp.get("xp_total"))],
                "consistency_raw": [
                    _num((m1.get("pillar_consistency") or {}).get("raw_score")),
                    _num(((pub or {}).get("pillar_consistency") or {}).get("raw_score")),
                ],
                "consistency_level": [
                    _num((m1.get("pillar_consistency") or {}).get("level")),
                    _num(((pub or {}).get("pillar_consistency") or {}).get("level")),
                ],
                "composite": [route_composite(cur), route_composite(new)],
                "character_xp": [_num(m1.get("character_xp")), _num((pub or {}).get("character_xp"))],
                "character_xp_debt": [_num(m1.get("character_xp_debt")), _num((pub or {}).get("character_xp_debt"))],
                "character_level": [_num(m1.get("character_level")), _num((pub or {}).get("character_level"))],
                "character_mood": [m1.get("character_mood"), (pub or {}).get("character_mood")],
                "relationships_xp_total": [
                    _num((m1.get("pillar_relationships") or {}).get("xp_total")),
                    _num(((pub or {}).get("pillar_relationships") or {}).get("xp_total")),
                ],
                "level_events": [_events(m1), _events(pub or {})],
                "verbatim_pillars_unchanged": unchanged,
                "presence": char[d].get("presence"),
                "method1_replay_mismatches": char[d].get("fidelity"),
                "sick_day_frozen_from": char[d].get("sick_day_frozen_from"),
                "order_fix": char[d].get("order_fix"),
            }
        )
        changed = any(rows[-1][f][0] != rows[-1][f][1] for f in ("character_level", "character_xp", "mind_level", "consistency_level"))
        rows[-1]["reasons"] = R.character_reasons(m1, pub, char[d].get("order_fix"), changed)
    return rows


def _events(rec: dict) -> list:
    return [
        f"{e.get('pillar') or 'character'}:{e.get('type')}:{e.get('old_level')}->{e.get('new_level')}"
        for e in rec.get("level_events") or []
    ]


def grade_rows(snap: dict, grades: dict) -> list:
    rows = []
    for d, g in sorted(grades.items()):
        item, pub = snap["grades"][d], g["public"]
        rows.append(
            {
                "date": d,
                "day_grade": [_num(item.get("total_score")), _num(pub.get("total_score"))],
                "letter": [item.get("letter_grade"), pub.get("letter_grade")],
                "journal_component": _num(item.get("component_journal")),
                "habits_mvp": [_num(g["habits"].get("stored")), _num(g["habits"].get("public"))],
                "habits_method": g["habits"].get("method"),
                "habits_policy": g["habits"].get("policy"),
                "habits_public_if_replay": _num(g["habits"].get("public_replay")),
                "day_grade_other_policy": (
                    list(g["habits"]["day_grade_other_policy"]) if g["habits"].get("day_grade_other_policy") else None
                ),
                "habits_replay_fidelity": g["habits"].get("fidelity"),
                "recap_card_letter": [
                    (snap["computed"].get(d) or {}).get("day_grade_letter"),
                    pub.get("letter_grade") if pub.get("total_score") is not None else None,
                ],
                "notes": g["notes"],
                "reasons": R.grade_reasons(item, g["habits"]),
            }
        )
    return rows


def _changed(pair) -> bool:
    return isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]


def summary(char_rows: list, g_rows: list) -> dict:
    fields = (
        "mind_raw",
        "mind_level",
        "composite",
        "character_xp",
        "character_level",
        "consistency_raw",
        "consistency_level",
        "character_mood",
        "level_events",
    )
    out: dict[str, Any] = {"character_dates": len(char_rows), "day_grade_dates": len(g_rows)}
    for f in fields:
        changed = [r["date"] for r in char_rows if _changed(r[f])]
        deltas = [abs(r[f][1] - r[f][0]) for r in char_rows if _changed(r[f]) and all(isinstance(x, (int, float)) for x in r[f])]
        out[f] = {
            "dates_changed": len(changed),
            "max_abs_delta": round(max(deltas), 4) if deltas else None,
            "first": changed[0] if changed else None,
            "last": changed[-1] if changed else None,
        }
    for f in ("day_grade", "letter", "habits_mvp", "recap_card_letter"):
        changed = [r["date"] for r in g_rows if _changed(r[f])]
        deltas = [abs(r[f][1] - r[f][0]) for r in g_rows if _changed(r[f]) and all(isinstance(x, (int, float)) for x in r[f])]
        out[f] = {"dates_changed": len(changed), "max_abs_delta": round(max(deltas), 4) if deltas else None}
    out["affected_dates"] = sorted(
        {r["date"] for r in char_rows if any(_changed(r[f]) for f in fields)}
        | {r["date"] for r in g_rows if _changed(r["day_grade"]) or _changed(r["letter"])}
    )
    out["verbatim_pillars_changed_dates"] = [r["date"] for r in char_rows if not r["verbatim_pillars_unchanged"]]
    out["method1_replay_mismatch_dates"] = [r["date"] for r in char_rows if r["method1_replay_mismatches"]]
    out["presence_inexact_dates"] = [r["date"] for r in char_rows if r["presence"] and not r["presence"]["exact"]]
    out["habits_replay_unfaithful_dates"] = [r["date"] for r in g_rows if r["habits_replay_fidelity"] is False]
    return out


# ── downstream aggregates ─────────────────────────────────────────────────────────────────


def weekly_means(g_rows: list, genesis: str) -> list:
    """story_dossier's day_grade_mean per experiment week (seven days from genesis), before/after."""
    weeks: dict[int, list] = {}
    for r in g_rows:
        n = (date.fromisoformat(r["date"]) - date.fromisoformat(genesis)).days // 7 + 1
        weeks.setdefault(n, []).append(r)
    out = []
    for n, rs in sorted(weeks.items()):
        a = [x["day_grade"][0] for x in rs if x["day_grade"][0] is not None]
        b = [x["day_grade"][1] for x in rs if x["day_grade"][1] is not None]
        out.append(
            {"week": n, "day_grade_mean": [round(statistics.fmean(a), 1) if a else None, round(statistics.fmean(b), 1) if b else None]}
        )
    return out


def _with_public_grades(series: dict, grades: dict) -> dict:
    """The weekly compute's series with each day's day_grade set to the RECOMPUTED public variant (the stored records
    carry none until the apply; the compute reads ``day_grade_public.public_score`` off them)."""
    for d, m in series.items():
        g = grades.get(d)
        m["day_grade"] = B.day_grade_public.public_score({B.PUBLIC: g["public"]}) if g else None
    return series


def _as_method1(series: dict, snap: dict, habitify: dict) -> dict:
    """The series as method 1 computed it: the stored method-1 day grade and the all-habits habit_pct."""
    from health import habit_pct_public

    for d, m in series.items():
        cm = snap["computed"].get(d) or {}
        m["day_grade"] = float(cm["day_grade_score"]) if cm.get("day_grade_score") is not None else None
        m["habit_pct"] = habit_pct_public.method1_habit_pct(habitify.get(d)) if habitify.get(d) else None
    return series


def correlation_aggregates(table, snap: dict, grades: dict) -> dict:
    """/api/correlations' day-grade pairs and /api/what_changed's day-grade monthly delta, recomputed over the stored
    window both ways (method-1 series vs public series), beside the stored (served) values."""
    from compute import weekly_correlation_compute_lambda as wcc

    stored = sorted(query_all(table, B.PFX + "weekly_correlations", "WEEK#0000", "WEEK#9999"), key=lambda i: i["sk"])
    latest = decimals_to_float(stored[-1]) if stored else {}
    start, end = latest.get("start_date"), latest.get("end_date")
    out: dict[str, Any] = {
        "weekly_correlations_week": latest.get("week") or str(latest.get("sk", "")).replace("WEEK#", ""),
        "window": [start, end],
    }
    if not (start and end):
        return out
    habitify = _dated(query_all(table, B.PFX + "habitify", f"DATE#{B.shift(end, -150)}", f"DATE#{end}~"))
    series_pub = _with_public_grades(wcc.assemble_daily_series(start, end), grades)
    series_m1 = _as_method1(copy.deepcopy(series_pub), snap, habitify)
    pairs = [p for p in wcc.CORRELATION_PAIRS if {"day_grade", "habit_pct"} & {p[0], p[1]}]
    a, b = wcc.compute_correlations(series_m1), wcc.compute_correlations(series_pub)
    served = latest.get("correlations") or {}
    out["pairs"] = {
        p[2]: {
            "served": {k: (served.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
            "recomputed_method1": {k: (a.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
            "recomputed_public": {k: (b.get(p[2]) or {}).get(k) for k in ("pearson_r", "n_days", "fdr_significant")},
        }
        for p in pairs
    }
    wc = decimals_to_float(table.get_item(Key={"pk": B.PFX + "what_changed", "sk": "SNAPSHOT#current"}).get("Item") or {})
    wc_end = wc.get("window_end") or end
    metric = [m for m in wcc._MONTH_DELTA_METRICS if m[0] in ("day_grade", "habit_pct")]
    lo = B.shift(wc_end, -60)
    s_pub = _with_public_grades(wcc.assemble_daily_series(lo, wc_end), grades)
    s_m1 = _as_method1(copy.deepcopy(s_pub), snap, habitify)
    out["what_changed_day_grade"] = {
        "window_end": wc_end,
        "served": [x for x in wc.get("deltas") or [] if x.get("metric") in ("day_grade", "habit_pct")],
        "recomputed_method1": wcc.compute_month_deltas(s_m1, wc_end, metrics=metric),
        "recomputed_public": wcc.compute_month_deltas(s_pub, wc_end, metrics=metric),
    }
    return out


class InjectingTable:
    """The real table (read-only use) with the ``public`` attribute of the character sheets and receipts replaced
    per sort key — how the route handlers are evaluated BEFORE (no injection: main's serving is simulated by a
    method-1 copy) and AFTER (the recomputed public variant), on the same stored records."""

    def __init__(self, real, inject: dict):
        self.real, self.inject = real, inject

    def _fix(self, item):
        if isinstance(item, dict) and item.get("pk") in self.inject:
            v = self.inject[item["pk"]].get(item.get("sk"))
            item = dict(item)
            item.pop(B.PUBLIC, None)
            if v is not None:
                item[B.PUBLIC] = v
        return item

    def query(self, **kw):
        resp = dict(self.real.query(**kw))
        resp["Items"] = [self._fix(i) for i in resp.get("Items", [])]
        return resp

    def get_item(self, **kw):
        resp = dict(self.real.get_item(**kw))
        if "Item" in resp:
            resp["Item"] = self._fix(resp["Item"])
        return resp

    def __getattr__(self, name):  # anything else (put/update/delete) is refused: this evaluation is read-only
        raise AttributeError(f"InjectingTable is read-only ({name})")


def latest_surfaces(snap: dict, char: dict) -> dict:
    """The latest-record surfaces (character_stats.json, /api/character_stats, /api/mind_overview's mind_pillar, the
    buddy page's character block), before (method 1, private pillar held) and after (the public variant)."""
    d = max(char)
    m1, pub = snap["sheets"][d], char[d]["public"]
    out: dict[str, Any] = {"as_of": d}
    for tag, view in (("before", served_view(m1, None)), ("after", served_view(m1, pub))):
        v = view or {}
        pillars = {
            p: {
                k: _num((v.get(f"pillar_{p}") or {}).get(k)) if k != "tier" else (v.get(f"pillar_{p}") or {}).get(k)
                for k in ("level", "raw_score", "tier", "xp_delta")
            }
            for p in ROUTE_PILLARS
        }
        out[tag] = {
            "character_stats": {
                "level": _num(v.get("character_level")),
                "tier": v.get("character_tier"),
                "xp_total": _num(v.get("character_xp")),
                "pillars": pillars,
            },
            "mind_pillar": {k: pillars["mind"][k] for k in ("level", "raw_score", "tier")},
            "buddy_character": {
                "level": _num(v.get("character_level")),
                "tier": v.get("character_tier"),
                "xp": _num(v.get("character_xp")),
                "events": _events(v),
            },
            "pillar_history_weekly_last7": _weekly_levels(snap, char, tag),
        }
    return out


def _weekly_levels(snap: dict, char: dict, tag: str) -> list:
    """character_stats.json's pillar_history: the last record of each ISO week (49 days), level_score per pillar."""
    end = max(char)
    lo = B.shift(end, -49)
    weeks: dict[str, tuple] = {}
    for d in sorted(char):
        if d < lo:
            continue
        view = served_view(snap["sheets"][d], None if tag == "before" else char[d]["public"]) or {}
        weeks[date.fromisoformat(d).strftime("%G-W%V")] = (d, view)
    return [
        {
            "week_end": d,
            "pillars": {
                p: round(float((v.get(f"pillar_{p}") or {}).get("level_score") or (v.get(f"pillar_{p}") or {}).get("raw_score") or 0), 1)
                for p in ROUTE_PILLARS
            },
        }
        for _w, (d, v) in sorted(weeks.items())
    ]


def _method1_as_public(m1: dict) -> dict:
    block = {k: v for k, v in m1.items() if k not in ("pk", "sk", "phase", "input_manifest", "input_status", "run_id")}
    block.update({"public_method_version": character_privacy.PUBLIC_METHOD_VERSION, "origin": "recomputed"})
    return block


def route_outputs(table, snap: dict, char: dict, receipts: dict) -> dict:
    """The served bodies of the character routes, before and after, evaluated by the routes' own handlers."""
    from web import site_api_character, site_api_discovery, site_api_journey, site_api_vitals

    def _body(resp, before):
        body = json.loads(resp["body"])
        body.pop("_meta", None)
        if before and isinstance(body.get("character"), dict):
            body["character"].pop("method", None)  # main serves no method label
        return body

    def _bodies(inject, before):
        g = dict(vars(site_api_vitals))
        g["table"] = InjectingTable(table, inject)
        out = {"character_latest": _body(site_api_character.character(None, _g=g), before)}
        out["timeline"] = _body(site_api_journey.timeline(_g=g), before)
        out["journey_timeline"] = _body(site_api_journey.journey_timeline(_g=g), before)
        out["pillar_coupling"] = _body(site_api_discovery.pillar_coupling(_g=g), before)
        if not before:
            out["character_receipt_latest"] = _body(site_api_character.character_receipt(max(char), False, _g=g), before)
        out["character_by_date"] = {}
        for d in sorted(char):
            body = _body(site_api_character.character(d, _g=g), before)
            out["character_by_date"][d] = {
                "level": body["character"].get("level"),
                "composite_score": body["character"].get("composite_score"),
                "xp_total": body["character"].get("xp_total"),
                "mind": next((p for p in body["pillars"] if p["name"] == "mind"), {}).get("raw_score"),
                "method": (body["character"].get("method") or {}).get("origin"),
            }
        return out

    before_inject = {B.SHEET_PK: {f"DATE#{d}": _method1_as_public(snap["sheets"][d]) for d in snap["sheets"]}}
    after_inject = {
        B.SHEET_PK: {f"DATE#{d}": r["public"] for d, r in char.items()},
        B.RECEIPT_PK: {f"DATE#{d}": v for d, v in receipts.items()},
    }
    return {"before": _bodies(before_inject, True), "after": _bodies(after_inject, False)}


# ── the CLI ───────────────────────────────────────────────────────────────────────────────


def _write(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, default=str)


def write_csv(path: str, rows: list) -> None:
    keys = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v for k, v in r.items()})


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="directory for the manifest / export (OUTSIDE the repo: it carries real values)")
    ap.add_argument("--to", default=(datetime.now(timezone.utc).date()).isoformat())
    ap.add_argument("--apply", action="store_true", help="WRITE: export the pre-image, then SET `public` (owner act)")
    ap.add_argument("--rollback", help="an export file: restore its pre-image (dry run unless --apply)")
    ap.add_argument("--skip-routes", action="store_true", help="skip the route-handler before/after evaluation")
    args = ap.parse_args(argv)

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    run_ts = datetime.now(timezone.utc).isoformat()

    if args.rollback:
        with open(args.rollback, encoding="utf-8") as fh:
            export = json.load(fh)
        result = B.rollback(table, export, apply=args.apply)
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}, indent=1))
        if args.out:
            _write(os.path.join(args.out, "rollback_result.json"), result)
        return 0 if not result["refused"] else 2

    if not args.out:
        ap.error("--out is required (a directory outside the repo)")
    os.makedirs(args.out, exist_ok=True)
    snap = load_snapshot(table, args.to)
    config = load_config(table, boto3.client("s3", region_name=region))
    char, receipts, grades = run_replays(snap, config, run_ts)
    c_rows, g_rows = character_rows(snap, char), grade_rows(snap, grades)
    manifest = {
        "generated_at": run_ts,
        "mode": "apply" if args.apply else "dry-run",
        "public_method_version": character_privacy.PUBLIC_METHOD_VERSION,
        "day_grade_public_method_version": B.day_grade_public.METHOD_VERSION,
        "summary": summary(c_rows, g_rows),
        "character": c_rows,
        "day_grade": g_rows,
        "story_dossier_day_grade_mean": weekly_means(g_rows, B.EXPERIMENT_START_DATE),
        "receipts": {"planned": len(receipts), "replay_verified": sum(1 for r in receipts.values() if r and r.get("replay_verified"))},
    }
    manifest["correlations_and_what_changed"] = correlation_aggregates(table, snap, grades)
    manifest["latest_surfaces"] = latest_surfaces(snap, char)
    h_rows = R.habit_pct_rows(snap["habitify"], snap["profile"].get("habit_registry") or {})
    manifest["habit_pct"] = {"method_version": R.habit_pct_public.METHOD_VERSION, "rows": h_rows}
    manifest["reasons_legend"] = R.REASONS
    manifest["historical_invariance"] = R.historical_invariance(snap, config, run_ts)
    manifest["public_habit_evidence"] = R.habit_evidence(snap, char, config)
    ledger = R.ledger_rows(c_rows, g_rows, h_rows, snap, run_ts)
    with open(os.path.join(args.out, "correction_ledger.jsonl"), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row, sort_keys=True, default=str) + "\n" for row in ledger)
    manifest["correction_ledger"] = {"rows": len(ledger), "file": "correction_ledger.jsonl", "format": R.LEDGER_VERSION}
    if not args.skip_routes:
        manifest["routes"] = route_outputs(table, snap, char, receipts)
    plan = B.plan_writes(char, grades, set(snap["receipts"]), receipts)
    without_habits = B.replay_character(snap["sheets"], snap["engagement"], snap["habit_scores"], config, run_ts, order_fix=False)
    ledger_item = B.public_corrections.build_ledger(
        {d: r["public"] for d, r in without_habits.items()}, {d: r["public"] for d, r in char.items()}, run_ts[:10]
    )
    _write(os.path.join(args.out, "public_correction_ledger.json"), ledger_item)
    stored = {(B.SHEET_PK, f"DATE#{d}"): r for d, r in snap["sheets"].items()}
    stored.update({(B.RECEIPT_PK, f"DATE#{d}"): r for d, r in snap["receipts"].items()})
    stored.update({(B.GRADE_PK, f"DATE#{d}"): r for d, r in snap["grades"].items()})
    manifest["plan"] = {
        "writes": len(plan),
        "by_partition": {pk: sum(1 for w in plan if w["pk"] == pk) for pk in {w["pk"] for w in plan}},
        # idempotency: planned values that differ from a public variant already stored (0 after an apply + re-run)
        "differs_from_stored_public": B.differs_from_stored(plan, stored),
    }
    _write(os.path.join(args.out, "manifest.json"), manifest)
    write_csv(os.path.join(args.out, "manifest_character.csv"), c_rows)
    write_csv(os.path.join(args.out, "manifest_day_grade.csv"), g_rows)
    _write(os.path.join(args.out, "plan.json"), plan)
    print(json.dumps(manifest["summary"], indent=1, default=str))
    if not args.apply:
        print(f"DRY RUN — nothing written. {len(plan)} planned writes; manifest in {args.out}")
        return 0
    export = B.build_export(lambda key: table.get_item(Key=key).get("Item"), plan, run_ts)
    export_path = os.path.join(args.out, f"export_{run_ts.replace(':', '')}.json")
    B.record_ledger_preimage(table, export)
    _write(export_path, export)  # the pre-image exists on disk BEFORE the first write
    result = B.apply_plan(table, plan, export)
    B.put_public_ledger(table, ledger_item)
    _write(os.path.join(args.out, "apply_result.json"), result)
    print(json.dumps({"written": result["written"], "skipped": len(result["skipped"]), "export": export_path}, indent=1))
    return 0 if not result["skipped"] else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
