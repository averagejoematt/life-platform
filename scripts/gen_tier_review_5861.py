#!/usr/bin/env python3
"""gen_tier_review_5861.py — the exercise-tier review, generated from the library's own rated taxonomy (#5861 fix round 13).

WHY. The earlier review copies were built from a hand-kept muscle-group list, so a rated target the list did not name (the
hip abductors, with an S-rated machine) had no section. Here NOTHING is listed by hand: every hypertrophy section is a
target id found on a rated row, every objective section is an objective in `quality_rubric.OBJECTIVES`, and the counts are
reconciled against the library's own `_provenance` before a line is written (a mismatch is a hard stop).

WHAT IT READS. `config/exercise_library.json` and `config/training_charter.json` (its `equipment.not_available` list) —
both public. No history, no overlay, nothing private: the output is safe to generate anywhere.

EVERY RATED ROW APPEARS ONCE, WHERE IT BELONGS. A movement that is a second Hevy template for the same exercise (an alias,
`variant.duplicate_of`) is folded into its canonical's line by name; a real variant keeps its own line and says what it is a
variant of. `review(lib, charter)` returns the structure the test checks; `render` turns it into markdown.

    python3 scripts/gen_tier_review_5861.py                 # markdown to stdout
    python3 scripts/gen_tier_review_5861.py --out FILE      # markdown to a file the caller names
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "lambdas"))

from training import library_integrity as integrity, quality_rubric as qr  # noqa: E402

LOCATION = integrity.LOCATION
TIERS = qr.QUALITY_TIERS
EVIDENCE_WORDS = {
    "rct_direct": "direct trial",
    "rct_characteristic": "related trial",
    "consensus": "consensus, no trial",
    "none_reviewed": "judgment, no study reviewed",
}
AVAILABILITY_WORDS = {
    "owner_confirmed": "owner-confirmed",
    "recent_inferred": "recent (inferred)",
    "historical_only": "historical only: not served",
    "unknown": "unknown: not served",
    "confirmed_unavailable": "confirmed unavailable",
}
REGIONS = ("upper", "lower", "core", "full_body", "cardio")


def _load(name: str) -> dict[str, Any]:
    with open(os.path.join(REPO_ROOT, "config", name), encoding="utf-8") as f:
        return json.load(f)


def _name(target: str) -> str:
    return str(target).replace("_", " ").capitalize()


def flags(lib: dict[str, Any], key: str, charter: dict[str, Any]) -> list[str]:
    """What a reader must know before reading the tier as servable: anchor, gated, availability, template, variant."""
    e = lib["movements"][key]
    out = []
    if e.get("family") == "strength_anchor":
        out.append("anchor")
    if integrity.locking_gates(lib, e):
        out.append("gated (locked)")
    evidence = ((e.get("availability") or {}).get(LOCATION) or {}).get("evidence")
    out.append(AVAILABILITY_WORDS.get(str(evidence), f"availability {evidence}"))
    if key in ((charter.get("equipment") or {}).get("not_available") or []):
        out.append("on the charter's not-available list")
    if integrity.unloggable(e):
        out.append("needs a Hevy template")
    elif e.get("logs_as"):
        out.append(f"logged as {e['logs_as']['movement_id']}")
    head = e.get("canonical") or key
    if head != key and not (e.get("variant") or {}).get("duplicate_of"):
        out.append(f"variant of {head}")
    return out


def _is_alias(e: dict[str, Any]) -> bool:
    return bool((e.get("variant") or {}).get("duplicate_of"))


def _rows(lib: dict[str, Any], charter: dict[str, Any], rated: list[tuple[str, dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """tier -> the rows of one section. `rated` is every (movement key, rating) the section holds; an alias whose
    canonical sits in the same tier of the same section folds into that line (`folded`), else it keeps its own."""
    mv = lib["movements"]
    tier_of = {k: r["tier"] for k, r in rated}
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in TIERS}
    folded: dict[str, list[str]] = {}
    for key, r in rated:
        head = str(mv[key].get("canonical") or key)
        if _is_alias(mv[key]) and tier_of.get(head) == r["tier"]:
            folded.setdefault(head, []).append(key)
            continue
        out[r["tier"]].append(
            {
                "key": key,
                "title": mv[key]["title"],
                "tier": r["tier"],
                "score": r.get("rubric_score"),
                "evidence": r.get("evidence_confidence"),
                "provisional": bool(r.get("provisional")),
                "flags": flags(lib, key, charter),
            }
        )
    for rows in out.values():
        for row in rows:
            row["folded"] = sorted(folded.get(row["key"], []))
        rows.sort(key=lambda x: (-(x["score"] or 0), x["title"].lower(), x["key"]))
    return out


def _section(sid: str, title: str, rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    counts = {t: sum(1 + len(r["folded"]) for r in rows[t]) for t in TIERS}
    return {"id": sid, "title": title, "counts": counts, "rows": rows}


def hypertrophy_sections(lib: dict[str, Any], charter: dict[str, Any]) -> list[dict[str, Any]]:
    """One section per target id found on a rated hypertrophy row — the JSON's own taxonomy, ordered by body region then
    name, a sub-target (`triceps_long_head`) straight after its parent."""
    by_target: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    region: dict[str, Counter[str]] = {}
    for key, e in lib["movements"].items():
        for r in e.get("hypertrophy") or []:
            if r.get("tier") in TIERS:
                by_target.setdefault(str(r["target"]), []).append((key, r))
                region.setdefault(str(r["target"]), Counter())[str((e.get("target") or {}).get("region"))] += 1
    parents = sorted(by_target, key=len)

    def parent(t: str) -> str:
        return next((p for p in parents if t != p and t.startswith(p + "_")), t)

    def order(t: str) -> tuple[int, str, int, str]:
        where = region[parent(t)].most_common(1)[0][0] if parent(t) in region else region[t].most_common(1)[0][0]
        return (REGIONS.index(where) if where in REGIONS else len(REGIONS), parent(t), int(t != parent(t)), t)

    return [_section(t, _name(t), _rows(lib, charter, by_target[t])) for t in sorted(by_target, key=order)]


def objective_section(lib: dict[str, Any], charter: dict[str, Any], objective: str) -> dict[str, Any]:
    rated = [(k, e["ratings"][objective]) for k, e in lib["movements"].items() if e["ratings"][objective]["tier"] in TIERS]
    return _section(objective, objective.capitalize(), _rows(lib, charter, rated))


def review(lib: dict[str, Any], charter: dict[str, Any]) -> dict[str, Any]:
    """The whole review as data. Raises when a count does not reconcile with the library's own `_provenance`."""
    mv, prov = lib["movements"], lib["_provenance"]
    hyp = hypertrophy_sections(lib, charter)
    others = [objective_section(lib, charter, o) for o in qr.OBJECTIVES if o != "hypertrophy"]
    rows_by_tier = {t: sum(s["counts"][t] for s in hyp) for t in TIERS}
    if rows_by_tier != {t: prov["hypertrophy_rows_by_tier"][t] for t in TIERS}:
        raise SystemExit(f"hypertrophy rows do not reconcile: sections {rows_by_tier}, library {prov['hypertrophy_rows_by_tier']}")
    for s in others:
        if s["counts"] != {t: prov["ratings_by_objective"][s["id"]][t] for t in TIERS}:
            raise SystemExit(f"{s['id']} does not reconcile: {s['counts']} vs {prov['ratings_by_objective'][s['id']]}")
    heads = sum(1 for k, e in mv.items() if (e.get("canonical") or k) == k)
    confidence = Counter(r["evidence_confidence"] for e in mv.values() for r in e["hypertrophy"] if r.get("tier") in TIERS)
    movement_confidence = Counter(
        e["ratings"]["hypertrophy"]["evidence_confidence"] for e in mv.values() if e["ratings"]["hypertrophy"]["tier"]
    )
    return {
        "version": lib["version"],
        "status": lib["status"],
        "rubric": lib["quality_rubric"]["version"],
        "movements": len(mv),
        "canonical": heads,
        "aliases": prov["canonical"]["aliases"],
        "variants": prov["canonical"]["variants"],
        "hypertrophy": hyp,
        "objectives": others,
        "hypertrophy_rows_by_tier": rows_by_tier,
        "hypertrophy_movements_by_tier": {t: prov["ratings_by_objective"]["hypertrophy"][t] for t in TIERS},
        "row_confidence": {c: confidence.get(c, 0) for c in qr.EVIDENCE_CONFIDENCE},
        "movement_confidence": {c: movement_confidence.get(c, 0) for c in qr.EVIDENCE_CONFIDENCE},
        "availability": dict(prov["integrity"]["movements_by_availability_evidence"]),
        "score_range": _score_range(mv),
    }


def _score_range(mv: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, list[int]] = {t: [] for t in TIERS}
    for e in mv.values():
        for r in e["hypertrophy"]:
            if r.get("tier") in TIERS:
                scores[r["tier"]].append(int(r["rubric_score"]))
    seen = sorted({s for v in scores.values() for s in v})
    top = int(max(qr.MAX_SCORE, qr.MAX_SCORE_COMPOUND))
    return {
        "by_tier": {t: [min(v), max(v)] if v else None for t, v in scores.items()},
        "never_occur": [s for s in range(0, top + 1) if s not in seen],
        "d_floor": next(floor for floor, tier in qr.BANDS if tier == "C"),
    }


# ── markdown ─────────────────────────────────────────────────────────────────
def _line(row: dict[str, Any], scored: bool) -> str:
    parts = [f"{row['title']} (`{row['key']}`)"]
    if scored:
        parts.append(f"{row['score']}")
    parts.append(EVIDENCE_WORDS.get(str(row["evidence"]), str(row["evidence"])))
    if row["provisional"]:
        parts.append("*provisional*")
    parts.append("_" + "; ".join(row["flags"]) + "_")
    if row["folded"]:
        parts.append("also logged as " + ", ".join(f"`{k}`" for k in row["folded"]))
    return "- " + " · ".join(parts)


def _render_section(s: dict[str, Any], level: str, scored: bool) -> list[str]:
    out = [f"{level} {s['title']} (`{s['id']}`): " + " · ".join(f"{t} {s['counts'][t]}" for t in TIERS), ""]
    for t in TIERS:
        if s["rows"][t]:
            out += [f"**{t}**"] + [_line(r, scored) for r in s["rows"][t]] + [""]
    return out


def render(r: dict[str, Any]) -> str:
    rc, mc, sr = r["row_confidence"], r["movement_confidence"], r["score_range"]
    rated_rows, rated_mv = sum(rc.values()), sum(mc.values())
    out = [
        f"# Exercise tiers: review copy (library v{r['version']}, rubric {r['rubric']}, status {r['status']})",
        "",
        f"Generated by `scripts/gen_tier_review_5861.py` from the library file alone. {r['movements']} movements: {r['canonical']} "
        f"canonical exercises, {r['aliases']} second templates for the same exercise (folded into their canonical's line) and "
        f"{r['variants']} variants (each on its own line). Nothing serves from this while the status is `proposed`.",
        "",
        "## What the ratings rest on",
        "",
        "A tier is a QUALITY judgment made by a written rubric from each movement's categorical inputs (how it loads the "
        "muscle's length, how stable it is, its resistance profile, how it progresses, what it costs the joints). It is not a "
        "study result, and evidence confidence is a separate label beside it.",
        "",
        f"- **{rc['none_reviewed']} of {rated_rows} rated hypertrophy rows ({mc['none_reviewed']} of {rated_mv} movements) are "
        "`judgment, no study reviewed`.** For these the tier is a biomechanical and practical judgment. No trial was reviewed, "
        "and none is implied. That is not a mark against the exercise: a row is never demoted for lacking a trial.",
        f"- {rc['rct_direct']} rows cite a trial of that movement for that muscle; {rc['rct_characteristic']} cite a trial of the "
        "characteristic they rely on (a range, a position), not of the movement itself. Only a direct trial moves a tier, by one "
        "band at most.",
        "- The strength, functional, conditioning and mobility ratings are rule-based practitioner judgments. `consensus` there "
        "means the inputs were checked by hand; no trial stands behind any single one.",
        "- *provisional* = an input is still unknown or was never checked by hand: a placeholder, not a verdict.",
        "",
        "**Why there is no D.** The scale runs 0 to "
        + str(max(qr.MAX_SCORE, qr.MAX_SCORE_COMPOUND))
        + f" and D is anything under {sr['d_floor']}. "
        "No rated hypertrophy row scores that low: the rows that would (jumps, drills, stretches, carries, cardio) are rated on "
        "their own objective and left blank here rather than forced into a muscle-growth tier, and a missing input scores the "
        "middle of its range, not zero. Scores that never occur: "
        + (", ".join(str(s) for s in sr["never_occur"]) or "none")
        + ". Observed range per tier: "
        + "; ".join(f"{t} {v[0]}–{v[1]}" if v else f"{t} none" for t, v in sr["by_tier"].items())
        + ". The bands overlap because categorical caps, not points, decide S and A: a row with S-level points is held at A or B "
        "when its load ceiling, its limiter or an S criterion says so. No D was assigned to fill a distribution.",
        "",
        "**Availability at home_gym** (five states, one per movement): "
        + "; ".join(f"{AVAILABILITY_WORDS[k]} {v}" for k, v in r["availability"].items())
        + ". Only owner-confirmed and recent equipment is served. `recent` is a heuristic: logged in the last "
        f"{integrity.RECENT_WINDOW_MONTHS} months.",
        "",
        "**Reading a line:** title (`library key`) · score · evidence confidence · flags. Flags: anchor, gated (locked), the "
        "availability state, needs a Hevy template, variant of. Hypertrophy lines carry the rubric score; the other objectives "
        "are rule-based and carry none.",
        "",
        "## Hypertrophy, by rated target",
        "",
        "Rows per tier: " + " · ".join(f"{t} {r['hypertrophy_rows_by_tier'][t]}" for t in TIERS) + f" ({rated_rows} rows). "
        "Movements by their primary target's tier: " + " · ".join(f"{t} {r['hypertrophy_movements_by_tier'][t]}" for t in TIERS) + ". "
        "A movement rated for two muscles appears in both sections.",
        "",
    ]
    for s in r["hypertrophy"]:
        out += _render_section(s, "###", scored=True)
    for s in r["objectives"]:
        out += _render_section(s, "##", scored=False)
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the markdown here (default: stdout)")
    args = ap.parse_args(argv)
    text = render(review(_load("exercise_library.json"), _load("training_charter.json")))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
