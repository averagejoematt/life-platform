"""tests/test_training_phases_charter_5574.py — the charter's `phases` section is references, not copies (#5574).

# premerge-gate: a contract test — every phase gate, unlock and hold in config/training_charter.json `phases` resolves to a charter path, carries no copied number, and the phase names match the Hevy title's

`config/training_charter.json` `phases` defines Foundation, Build, Forge and Sustain: an intent, entry gates as
machine-readable predicates and the unlocks of each (the #5574 ruling, recorded on the issue 2026-11-02). The
section's promise is that a gate VALUE is never a second copy of a charter number: a weight gate names
`gated_movements.conventional_deadlift.gate_lb`, it does not say 275. This file holds that promise:

  * every `value_ref` / `gate_ref` / `unlocks` / `until_then` / `held_for` resolves in the public charter, or
    (for a value that is owner-only) is an `owner_twin:` alias that maps to a path the committed example twin
    (#5087) documents — the reference resolves, and neither the value nor the twin's key name enters the charter;
  * every gate has an id, a metric and a comparator, and a `value`, `value_ref` or `gate_ref` (never value and value_ref both);
    a `value` is never a number (a numeric gate value would be a hand copy the derivation guard cannot key);
  * `order` names every definition once, and the titles are the Hevy title's phases
    (`config/training_phases.json` `phases`, ADR-067) in the same order.

The numbers the section does own (the advance and every_transition rules) are swept by
tests/test_training_charter_derivation_5068.py's LEAF_PATTERNS. Negative controls below mutate a copy of the
section and assert the checker names each fault.
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
from typing import Any, List

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import training_charter as tc  # noqa: E402
from training.phase_evaluator import OWNER_TWIN_REFS  # noqa: E402  (#5575: the ONE alias map, the evaluator's)

_CHARTER = json.loads((_REPO / "config" / "training_charter.json").read_text())
_EXAMPLE_TWIN = json.loads((_REPO / "config" / "training_charter.private.example.json").read_text())
_TITLE_PHASES = json.loads((_REPO / "config" / "training_phases.json").read_text())["phases"]

_REF_KEYS = ("value_ref", "gate_ref", "held_for")
_INDEX = re.compile(r"^(.*)\[(\d+)\]$")


def _resolve(doc: Any, dotted: str) -> bool:
    cur = doc
    for part in dotted.split("."):
        m = _INDEX.match(part)
        key, idx = (m.group(1), int(m.group(2))) if m else (part, None)
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
        if idx is not None:
            if not isinstance(cur, list) or idx >= len(cur):
                return False
            cur = cur[idx]
    return True


# An owner-only value is referenced by an alias, never by its twin path: the owner prompt block carries the whole
# public charter and must not name a private-twin key (tests/test_charter_ai_budget_5084.py). The alias resolves
# here, against the committed example twin's SHAPE, through the evaluator's own map (`training.phase_evaluator`,
# #5575) — one map, so the contract and the reader cannot disagree about where an alias points.


def _ref_ok(charter: dict, ref: str, where: str) -> List[str]:
    if ref.startswith("owner_twin:"):
        twin_path = OWNER_TWIN_REFS.get(ref)
        if twin_path is None or twin_path.split(".")[0] not in tc.PRIVATE_KEYS or not _resolve(_EXAMPLE_TWIN, twin_path):
            return [f"{where}: private ref {ref!r} not documented by the example twin"]
        return []
    target = ref if not ref.startswith("advance.") else f"phases.{ref}"
    return [] if _resolve(charter, target) else [f"{where}: ref {ref!r} resolves to nothing in the charter"]


def check(charter: dict) -> List[str]:
    problems: List[str] = []
    ph = charter.get("phases")
    if not isinstance(ph, dict):
        return ["charter has no `phases` section"]
    defs = ph.get("definitions", {})
    order = ph.get("order", [])
    if sorted(order) != sorted(defs) or len(set(order)) != len(order):
        problems.append(f"order {order} does not name each definition {sorted(defs)} exactly once")
    titles = [defs[i].get("title") for i in order if i in defs]
    if titles != list(_TITLE_PHASES):
        problems.append(f"titles {titles} != the Hevy title's phases {_TITLE_PHASES} (config/training_phases.json)")
    gates = []
    for pid, d in defs.items():
        for key in ("entry_gates", "entry_gates_any_of"):
            gates += [(f"definitions.{pid}.{key}", g) for g in d.get(key, [])]
        for key in ("unlocks", "until_then"):
            for ref in d.get(key, []):
                problems += _ref_ok(charter, ref, f"definitions.{pid}.{key}")
    gates += [(f"every_transition.{gid}", dict(g, id=gid)) for gid, g in ph.get("every_transition", {}).items()]
    for where, g in gates:
        for need in ("id", "metric", "comparator"):
            if not g.get(need):
                problems.append(f"{where}: gate without {need!r}")
        if "every_transition" not in where and not any(k in g for k in ("value", "value_ref", "gate_ref")):
            problems.append(f"{where}: needs a value, a value_ref or a gate_ref")
        if "value" in g and "value_ref" in g:
            problems.append(f"{where}: carries both value and value_ref")
        v = g.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            problems.append(f"{where}: numeric value {v!r} is a hand copy — reference the charter path instead")
        for k in _REF_KEYS:
            if k in g:
                problems += _ref_ok(charter, g[k], f"{where}.{k}")
    return problems


def test_the_live_phases_section_holds_the_contract():
    assert check(_CHARTER) == []


def test_the_first_phase_has_no_entry_gate_and_every_later_one_has_one():
    defs, order = _CHARTER["phases"]["definitions"], _CHARTER["phases"]["order"]
    assert not defs[order[0]].get("entry_gates") and not defs[order[0]].get("entry_gates_any_of")
    for pid in order[1:]:
        assert defs[pid].get("entry_gates") or defs[pid].get("entry_gates_any_of"), pid


def test_the_label_never_regresses_and_advance_waits_for_a_block_start():
    adv = _CHARTER["phases"]["advance"]
    assert adv["regression"] is False and adv["takes_effect"] == "next_block_start"
    assert adv["owner_veto"] is True and adv["owner_override"] is True


def test_phases_is_not_on_the_published_whitelist():
    assert not any(w == "phases" or w.startswith("phases.") for w in tc.PUBLISHED_WHITELIST)


# ---- negative controls: each mutation is named by the checker ----


def _mutated(fn) -> List[str]:
    c = copy.deepcopy(_CHARTER)
    fn(c["phases"])
    return check(c)


def test_a_copied_gate_number_is_named():
    def m(ph):
        g = ph["definitions"]["build"]["entry_gates"][0]
        g.pop("value_ref")
        g["value"] = 275

    assert any("hand copy" in p for p in _mutated(m))


def test_a_dangling_ref_is_named():
    def m(ph):
        ph["definitions"]["forge"]["unlocks"].append("cardio_menu.blocks.sprints")

    assert any("resolves to nothing" in p for p in _mutated(m))


def test_an_undocumented_private_ref_is_named():
    def m(ph):
        ph["definitions"]["sustain"]["entry_gates_any_of"][1]["value_ref"] = "owner_twin:goal_waist"

    assert any("private ref" in p for p in _mutated(m))


def test_a_renamed_phase_is_named():
    def m(ph):
        ph["definitions"]["forge"]["title"] = "Develop"

    assert any("Hevy title" in p for p in _mutated(m))


def test_a_gate_without_a_comparator_is_named():
    def m(ph):
        ph["every_transition"]["consistency"].pop("comparator")

    assert any("comparator" in p for p in _mutated(m))
