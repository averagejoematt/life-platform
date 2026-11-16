"""training_notes_deviation.py — the pure pushed-vs-performed diff of the note layer (brief §14.1).

Moved verbatim out of `training_notes.py` (#5573, for the #1665 module-size ceiling) and re-exported there, so
`training_notes.compute_deviation` is unchanged for every caller. No I/O, no model.
"""

from __future__ import annotations


def compute_deviation(pushed_exercises, performed_exercises) -> dict:
    """Pure diff of the pushed routine vs the performed workout (brief §14.1). No LLM.

    Returns {by_template: {tid: deviation_signal}, added: [...], removed: [...]} — a
    durable preference/capacity signal (consistently adds a 4th set, swaps DB→barbell).
    Keyed by template_id so it folds into the exercise-keyed projection.
    """

    def _index(exs):
        out = {}
        for e in exs or []:
            tid = str(e.get("template_id") or e.get("movement_key") or "")
            if not tid:
                continue
            sets = e.get("sets") or []
            out[tid] = {"name": e.get("name") or e.get("title") or "", "set_count": len(sets)}
        return out

    pushed, performed = _index(pushed_exercises), _index(performed_exercises)
    by_template, added, removed = {}, [], []
    for tid, p in performed.items():
        if tid not in pushed:
            added.append({"template_id": tid, "name": p["name"]})
            continue
        sd = p["set_count"] - pushed[tid]["set_count"]
        if sd:
            by_template[tid] = {
                "class": "deviation",
                "summary": f"performed {p['set_count']} sets vs {pushed[tid]['set_count']} prescribed",
                "confidence": 1.0,
                "value": {"set_delta": sd},
            }
    for tid, p in pushed.items():
        if tid not in performed:
            removed.append({"template_id": tid, "name": p["name"]})
    return {"by_template": by_template, "added": added, "removed": removed}
