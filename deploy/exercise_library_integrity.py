"""exercise_library_integrity.py — the builder's half of the library-integrity rules (#5861 fix round 13).

`training.library_integrity` states the rules and checks the built library; this module APPLIES them while building:

  * TEMPLATES (`deploy/exercise_library_templates.json`, data only): a created custom template makes its movement
    loggable; a canonical mapping records which family member's template a template-less movement is logged under; a
    released template id is never adopted from the movement catalog; and every movement the Hevy record still cannot
    represent is stamped `not_for_you_now` (`library_integrity.UNLOGGABLE_CODE`), whatever else it carries.
  * CANDIDATE TITLES: an expansion candidate that names a template id records the title that template carries in Hevy. A
    candidate whose title differs must say why — the check that would have caught a candidate pointing at a different
    exercise's template (a near-identical custom id).
  * AVAILABILITY: the five evidence states for every equipment id and movement, from the history summary the builder
    already reads. No log date is written: a row carries its state and the rule that gave it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from training import library_integrity as rules

TEMPLATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exercise_library_templates.json")
UNLOCK = (
    "its custom Hevy template is created (owner ruling 2026-11-14: every exercise missing from Hevy gets one) and the id is "
    "recorded in deploy/exercise_library_templates.json; then a movement-catalog entry"
)


def load_templates(path: str | None = None) -> dict[str, Any]:
    with open(path or TEMPLATES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {k: data.get(k) or {} for k in ("created", "canonical_mappings", "released", "hevy_titles")}


def released_ids(templates: dict[str, Any]) -> set[str]:
    return {str(t).upper() for t in templates["released"]}


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def candidate_title_errors(candidates: list[dict[str, Any]], templates: dict[str, Any]) -> list[str]:
    """Every template-bearing candidate records its template's Hevy title; a title that is not the candidate's own needs
    its reason; no candidate may name a released template."""
    out: list[str] = []
    titles = {str(k).upper(): v for k, v in templates["hevy_titles"].items()}
    for x in candidates:
        tid = str(x.get("template_id") or "").upper()
        if not tid:
            continue
        if tid in released_ids(templates):
            out.append(f"{x['key']}: template {tid} is released ({templates['released'][tid]['why']})")
        row = titles.get(tid)
        if not isinstance(row, dict) or not row.get("title"):
            out.append(f"{x['key']}: no recorded Hevy title for template {tid} (hevy_titles)")
        elif _norm(row["title"]) != _norm(x["title"]) and not row.get("differs_because"):
            out.append(f"{x['key']}: is {x['title']!r} but template {tid} is {row['title']!r} in Hevy, with no reason recorded")
    return out


def index_title_errors(templates: dict[str, Any], index_path: str) -> list[str]:
    """Against a copy of the live Hevy template index (read-only): every recorded title is the index's title for that id."""
    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)
    live = {str(t.get("id") or "").upper(): str(t.get("title") or "") for t in (idx.get("templates") or {}).values()}
    rows = {str(k).upper(): v for k, v in templates["hevy_titles"].items()}
    rows |= {str(v["template_id"]).upper(): v for v in templates["created"].values()}
    out = []
    for tid, row in sorted(rows.items()):
        if tid not in live:
            out.append(f"hevy_titles.{tid}: not in the Hevy template index")
        elif _norm(live[tid]) != _norm(row["title"]):
            out.append(f"hevy_titles.{tid}: recorded {row['title']!r}, Hevy has {live[tid]!r}")
    return out


def apply_templates(movements: dict[str, dict[str, Any]], tid_to_key: dict[str, str], templates: dict[str, Any]) -> None:
    """In place, before gates resolve: created templates, canonical mappings, then the structural stamp on every movement
    the Hevy record cannot represent. A row that does not fit is a hard stop — a template fact never vanishes silently."""
    for key, row in templates["created"].items():
        e = movements.get(key)
        if e is None or e.get("template_id") or not row.get("template_id") or not row.get("title"):
            raise SystemExit(f"templates.created.{key}: needs a template-less library movement, a template_id and its Hevy title")
        e["template_id"] = str(row["template_id"])
        e["template_note"] = f"custom Hevy template {row['title']!r}, created after the owner ruling of 2026-11-14"
        tid_to_key[str(row["template_id"]).upper()] = key
        if (e.get("not_for_you_now") or {}).get("reason_code") == rules.UNLOGGABLE_CODE:
            e["not_for_you_now"] = None
    for key, row in templates["canonical_mappings"].items():
        e, head = movements.get(key), movements.get(str(row.get("logs_as")))
        if e is None or head is None or e.get("template_id") or not head.get("template_id"):
            raise SystemExit(f"templates.canonical_mappings.{key}: needs a template-less movement and a templated one to log under")
        e["logs_as"] = {"movement_id": row["logs_as"], "template_id": head["template_id"], "why": row["why"]}
    for key, e in movements.items():
        if not rules.unloggable(e):
            continue
        other = (e.get("not_for_you_now") or {}).get("reason_code")
        if other not in (None, rules.UNLOGGABLE_CODE):
            raise SystemExit(f"{key}: not loggable, but already not_for_you_now for {other}")
        e["not_for_you_now"] = {"reason_code": rules.UNLOGGABLE_CODE, "unlock_condition": UNLOCK}


# ── availability ─────────────────────────────────────────────────────────────
WINDOW = f"the last {rules.RECENT_WINDOW_MONTHS} months of the Hevy history"
INVENTORY_RULE = (
    "owner rulings 2026-11-11 and 2026-11-14: every equipment id carries one of five evidence states for home_gym — "
    "owner_confirmed, recent_inferred, historical_only, unknown, confirmed_unavailable — and `state` follows from it: only "
    "owner_confirmed and recent_inferred are `available`. recent_inferred is a HEURISTIC: used by a movement logged in "
    f"{WINDOW} (the window ends on the history's last workout); used only by older logs is historical_only; never logged is "
    "unknown. The basic classes (`basic: true` — free weights, flat and adjustable benches, the rack, cable stations, the "
    "pull-up bar, bands, bodyweight) are inferred as a class and never confirmed one by one. A 'gym doesn't have X' note, or "
    "an owner ruling, overrides the logs. Contention ('X was taken') never changes a state. The gym is never named."
)


def _months_before(day: str, months: int) -> str:
    y, m, d = (int(x) for x in day.split("-"))
    total = y * 12 + (m - 1) - months
    return f"{total // 12:04d}-{total % 12 + 1:02d}-{min(d, 28):02d}"


def home_gym_inventory(movements: dict[str, dict[str, Any]], history: dict[str, Any], seeds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Equipment id -> {home_gym: {state, evidence, source[, basic]}} (`library_integrity` rule 2). Deterministic: the
    window ends on the history's own last workout. A seed (an owner note or ruling) wins over the logs."""
    cutoff = _months_before(history.get("last") or "1970-01-01", rules.RECENT_WINDOW_MONTHS)
    logged = [e for e in movements.values() if e.get("history")]
    recent = {x for e in logged if e["history"].get("last_done", "") >= cutoff for x in e["equipment"]}
    older = {x for e in logged for x in e["equipment"]}
    out: dict[str, Any] = {}
    for eid in sorted({x for e in movements.values() for x in e["equipment"]}):
        basic = eid in rules.BASIC_EQUIPMENT
        if eid in seeds:
            row = dict(seeds[eid])
        elif basic:
            row = {"evidence": "recent_inferred", "source": f"heuristic: a basic class, inferred as a class from {WINDOW}"}
        elif eid in recent:
            row = {"evidence": "recent_inferred", "source": f"heuristic: used by a movement logged in {WINDOW}"}
        elif eid in older:
            row = {"evidence": "historical_only", "source": f"used only by movements logged before {WINDOW}"}
        else:
            row = {"evidence": "unknown", "source": "never logged: named only by expansion candidates"}
        row = {"state": rules.EVIDENCE_STATE[row["evidence"]], **row}
        out[eid] = {rules.LOCATION: row | ({"basic": True} if basic else {})}
    return out


def movement_availability(e: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    """A movement's evidence is the worst of its equipment's, and its state follows; the source names what decided it."""
    rows = {x: inventory[x][rules.LOCATION] for x in e["equipment"]}
    evidence = rules.worst_evidence([r["evidence"] for r in rows.values()])
    deciding = sorted(x for x, r in rows.items() if r["evidence"] == evidence)
    return {"state": rules.EVIDENCE_STATE[evidence], "evidence": evidence, "source": "the worst of its equipment: " + ", ".join(deciding)}
