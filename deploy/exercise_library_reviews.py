"""exercise_library_reviews.py — the accepted evidence-review ledger for the exercise library (#5778).

`scripts/library_evidence_review.py` proposes library changes once per block; the owner accepts them by MERGING
its PR. What the PR carries is two things: the edited `config/exercise_library.json`, and one appended record in
`deploy/exercise_library_reviews.json` (this module's ledger). The ledger is what makes an accepted review survive a
rebuild: `deploy/build_exercise_library.py` re-applies every record on top of the curation module, so
`build_exercise_library.py --write` and the review script produce the same rows.

A record carries, all verified live by the review script before it could be written:

  * `citations`    — {citation_id: record}; a later record with the same id is a correction and wins.
  * `evidence_changes` — [{movement, target, evidence_confidence, evidence_adjustment?, citations, last_reviewed,
                     note?}]; the EVIDENCE half of the row for that target is replaced (or a row appended when the movement
                     has none for it). The quality tier is never written here: the builder re-derives it from the rubric
                     (`training.quality_rubric`, #5857), moved at most one band by a recorded direct-trial adjustment.
  * `candidates`   — expansion-candidate dicts in the curation module's `_x(...)` shape (key, title,
                     template_id, attributes, hypertrophy, gates); the builder adds them beside `EXPANSION`.

Pure functions, no I/O beyond `load_ledger`. The ledger never holds a load, a bodyweight or a note: the library
it edits is the public half.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exercise_library_reviews.json")

EMPTY_LEDGER: dict[str, Any] = {
    "_README": (
        "Accepted evidence reviews of config/exercise_library.json (#5778). Appended ONLY by "
        "scripts/library_evidence_review.py on a PR branch the owner merges; deploy/build_exercise_library.py re-applies "
        "every record so a rebuild keeps them. Every citation here resolved live (Crossref DOI / PubMed PMID) with a "
        "matching title, first author and year on its review date. Never hand-edit; never a load, bodyweight or note."
    ),
    "reviews": [],
}


def load_ledger(path: str = LEDGER_PATH) -> dict[str, Any]:
    """The ledger on disk, or the empty ledger when the file does not exist yet."""
    if not os.path.exists(path):
        return copy.deepcopy(EMPTY_LEDGER)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("reviews", [])
    return data


def ledger_citations(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every accepted citation, later records winning (a correction re-registers the same id)."""
    out: dict[str, dict[str, Any]] = {}
    for rec in ledger.get("reviews") or []:
        for cid, c in (rec.get("citations") or {}).items():
            out[cid] = dict(c)
    return out


def ledger_candidates(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Every accepted expansion candidate, in acceptance order; a later record with the same key replaces it."""
    by_key: dict[str, dict[str, Any]] = {}
    for rec in ledger.get("reviews") or []:
        for x in rec.get("candidates") or []:
            by_key[x["key"]] = copy.deepcopy(x)
    return list(by_key.values())


def ledger_evidence_changes(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(t) for rec in ledger.get("reviews") or [] for t in rec.get("evidence_changes") or []]


def evidence_row(change: dict[str, Any]) -> dict[str, Any]:
    """The evidence half of the library row a change writes (the curation module's `hyp()` shape). The tier fields are
    derived afterwards by `quality_rubric.finalize_row`."""
    row: dict[str, Any] = {
        "target": change["target"],
        "evidence_confidence": change["evidence_confidence"],
        "citations": list(change.get("citations") or []),
        "last_reviewed": change["last_reviewed"],
    }
    if change.get("evidence_adjustment"):
        row["evidence_adjustment"] = dict(change["evidence_adjustment"])
    if change.get("note"):
        row["note"] = change["note"]
    return row


def apply_evidence_changes(movements: dict[str, dict[str, Any]], changes: list[dict[str, Any]]) -> list[str]:
    """Write each change's evidence row into `movements` in place. Returns the changes whose movement is not in the
    library (the builder treats that as a hard stop; the review script refuses the proposal). The caller re-derives the
    quality tier (`finalize_tiers`)."""
    missing: list[str] = []
    for ch in changes:
        e = movements.get(ch["movement"])
        if e is None:
            missing.append(f"{ch['movement']}:{ch['target']}")
            continue
        row = evidence_row(ch)
        rows = list(e.get("hypertrophy") or [])
        for i, r in enumerate(rows):
            if r.get("target") == ch["target"]:
                rows[i] = row
                break
        else:
            rows.append(row)
        e["hypertrophy"] = rows
    return missing


def finalize_tiers(movements: dict[str, dict[str, Any]]) -> None:
    """Every row's quality tier re-derived from the rubric plus its recorded evidence adjustment (#5857), and every
    objective rating from the #5861 rubrics (`ratings`, null where an objective does not apply), in place."""
    from training import quality_rubric

    for e in movements.values():
        e["hypertrophy"] = [quality_rubric.finalize_row(e, r) for r in e.get("hypertrophy") or []]
    apply_evidence_ordering(movements)
    apply_s_quota(movements)
    for e in movements.values():
        e["ratings"] = quality_rubric.objective_ratings(e)


def _holder(keys: list[str], family: str, movements: dict[str, dict[str, Any]]) -> str:
    """The member that keeps a family's S: the canonical movement itself when it earned S, else the one he has done most
    (history exposures), else the first by key — deterministic."""
    if family in keys:
        return family
    return sorted(keys, key=lambda k: (-int(((movements[k].get("history") or {}).get("exposures")) or 0), k))[0]


def _is_variant(e: dict[str, Any]) -> bool:
    """A real variant of its family (a grip, stance, range, implement or laterality difference) — not an exact duplicate."""
    v = e.get("variant")
    return isinstance(v, dict) and bool(v) and "duplicate_of" not in v


def apply_s_quota(movements: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """#5861 FIX3 (third red team: 49 hypertrophy S, every lat-pulldown grip S): ONE S per canonical family per objective (per
    target muscle for hypertrophy). An exact duplicate (another Hevy template of the same movement) shares its canonical's
    rating; every other member — a real variant — that earned S carries an `s_quota` {holder, family} — on its hypertrophy
    row, or under `s_quota[objective]` on the entry — and the rubric caps it at A with the line naming the holder
    (`quality_rubric.s_quota_why`): a grip or stance variant is shown as the holder's variant, not a second S. Re-derived from
    scratch on every build (idempotent). Returns {objective|family|target: {holder, demoted}} — the report."""
    from training import quality_rubric

    for e in movements.values():
        e.pop("s_quota", None)
        e["hypertrophy"] = [
            quality_rubric.finalize_row(e, {k: v for k, v in r.items() if k != "s_quota"}) for r in e.get("hypertrophy") or []
        ]
    groups: dict[tuple[str, str, str], list[str]] = {}
    for key, e in sorted(movements.items()):
        fam = str(e.get("canonical") or key)
        for r in e.get("hypertrophy") or []:
            if r.get("tier") == "S":
                groups.setdefault(("hypertrophy", fam, str(r.get("target"))), []).append(key)
        rated = quality_rubric.objective_ratings(e)
        for obj in quality_rubric.OBJECTIVES:
            if obj != "hypertrophy" and (rated.get(obj) or {}).get("tier") == "S":
                groups.setdefault((obj, fam, ""), []).append(key)
    report: dict[str, dict[str, Any]] = {}
    for (obj, fam, target), keys in sorted(groups.items()):
        if len(keys) < 2:
            continue
        same = [k for k in keys if not _is_variant(movements[k])]  # the canonical and its exact duplicates: one movement
        holder = fam if fam in keys else (same[0] if same else _holder(keys, fam, movements))
        quota = {"holder": holder, "family": fam}
        for k in keys:
            if k == holder or (k in same and holder in same):
                continue  # an exact duplicate (another Hevy template of the same movement) carries its canonical's rating
            e = movements[k]
            if obj == "hypertrophy":
                e["hypertrophy"] = [
                    quality_rubric.finalize_row(e, r | {"s_quota": dict(quota)}) if str(r.get("target")) == target else r
                    for r in e["hypertrophy"]
                ]
            else:
                e.setdefault("s_quota", {})[obj] = dict(quota)
        demoted = sorted(k for k in keys if k != holder and not (k in same and holder in same))
        if demoted:
            report["|".join(x for x in (obj, fam, target) if x)] = {"holder": holder, "demoted": demoted}
    return report


def apply_evidence_ordering(movements: dict[str, dict[str, Any]]) -> None:
    """#5861 FIX2-DATA: each untested form of a trial-backed movement (`exercise_library_input_review.EVIDENCE_FORMS`)
    carries the tested row's tier as its `evidence_ceiling` for the trial's target, and is re-derived under it. Runs after
    every row is final, so the tested tier is the one the library ships. A form with its own direct trial is left alone."""
    import exercise_library_input_review as input_review
    from training import quality_rubric

    for tested, spec in input_review.EVIDENCE_FORMS.items():
        anchor = next((r for r in movements[tested]["hypertrophy"] if r.get("target") == spec["target"]), None)
        ceiling = quality_rubric.evidence_ceiling(anchor or {}, tested)
        for form in spec["forms"]:
            e = movements[form]
            rows = []
            for r in e.get("hypertrophy") or []:
                r = {k: v for k, v in r.items() if k != "evidence_ceiling"}
                if ceiling and r.get("target") == spec["target"] and r.get("evidence_confidence") not in quality_rubric.EVIDENCE_ADJUSTERS:
                    r["evidence_ceiling"] = dict(ceiling)
                rows.append(quality_rubric.finalize_row(e, r))
            e["hypertrophy"] = rows
