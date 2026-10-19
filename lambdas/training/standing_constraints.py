"""training/standing_constraints.py — the plan-shaping standing constraints a draft must obey (#5000).

WHY THIS EXISTS

The 2026-10-18 draft (routine `2167c0e68e25f311d46f1015cbefc047`) was authored as if nothing had
changed on 2026-10-10. Its first exercise carried the Whoop recovery-band cues (🟢 67-100 / 🟡
34-66 / 🔴 1-33) although the standing constraint of 2026-10-10 (the HR regime change) makes every
HR-derived tier invalid across that boundary and gates the session on that morning's ECG plus feel,
and its `cardio_pick` carried an HR ceiling and an HR target although the same constraint forbids HR
prescriptions (the talk test applies). The constraint lived only as a free-text platform-memory note,
so the deterministic draft path could not see it.

WHAT LIVES HERE (and what does not)

This repo is public. The constraint's clinical specifics stay owner-only in platform memory (the row
named by `memory_sk`); this module carries only what the draft path has to ACT on — the date it took
effect, that it invalidates HR-derived tiers, that it forbids HR prescriptions, and the gate's two RPE
caps — each with its provenance (ADR-105). The stop list itself is read from the memory row at draft
time (`mcp.draft_standing_constraint.read_standing_constraint`); this module only says which numbered rule
of that row carries it. Pure: no I/O, no boto3, stdlib only.

`training_context_registry.RECORDED_CONSTRAINTS` (#3715) is the INJURY list a coach reads before
prescribing load, under its own gate:owner review date; this is the sibling list of constraints that
change HOW a session is gated. Kept apart so neither list's review posture silently covers the other.
"""

from __future__ import annotations

import re
from typing import Any

ISSUE = "#5000"

# The talk test, in the words the owner's hand-built 2026-10-18 routine used (owner-history).
TALK_TEST_CUE = "talk test — full sentences throughout. No HR target."
HR_PICK_FIELDS = ("hr_ceiling_bpm", "hr_target_bpm")

STANDING_CONSTRAINTS: list[dict[str, Any]] = [
    {
        "id": "hr_regime_change_2026_10_10",
        "kind": "clinical_event",
        "detail": "the standing constraint of 2026-10-10 (the HR regime change); the specifics are owner-only in platform memory",
        "memory_sk": "MEMORY#training#2026-10-10#1c0bee61d2",
        "active_from": "2026-10-10",
        # "until Matthew or his clinician says otherwise" — no end date is on the record, so none is invented.
        "active_until": None,
        "invalidates_hr_tiers": True,
        "hr_prescriptions_allowed": False,
        # The intensity half of this constraint (the cardio "no push" rule) is retired from this day on:
        # the owner ruling of 2026-10-18 (ruling 7) and his guidance record of the same day open intervals
        # and conditioning, prescribed by RPE / talk test. The HR half (no HR-derived tier, no HR target)
        # stays in force. The lifting ECG + feel gate (`gate_lines`) is #5059's to retire.
        "intensity_gate_retired_from": "2026-10-18",
        "gate": {
            "kind": "ecg_and_feel",
            "sinus_rpe_cap": 8,
            "not_sinus_rpe_cap": 7,
            "optional_when_not_sinus": ("accessory", "cardio"),
        },
        # The memory row is a numbered rule list; rule (4) is the stop list.
        "stop_list_rule": 4,
        "provenance": {
            "invalidates_hr_tiers": "owner — platform memory 2026-10-10, rule (1)",
            "hr_prescriptions_allowed": "owner — platform memory 2026-10-10, rule (2): the talk test",
            "not_sinus_rpe_cap": "owner — platform memory 2026-10-10, rule (1)",
            "sinus_rpe_cap": "owner — the 2026-10-18 brief §A2 / issue #5000 (the plan as written, every set at RPE 8 or below)",
            "cardio_minutes": "owner-history — the hand-built 2026-10-18 routine (014e1142…): recumbent, 20 min",
            "intensity_gate_retired_from": "owner — ruling 7 of 2026-10-18 (#5067): intervals and conditioning open, by RPE / talk test",
        },
    },
]


def active_constraint(target_date: str, constraints: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """THE reader: the standing constraint that invalidates HR-derived tiers on `target_date`, or None.

    Day keys compare as ISO strings (#3609). A constraint with no `active_until` stays active — the
    record says "until the owner or his clinician says otherwise", never a guessed expiry."""
    day = str(target_date or "")[:10]
    for c in STANDING_CONSTRAINTS if constraints is None else constraints:
        if not c.get("invalidates_hr_tiers"):
            continue
        if str(c.get("active_from") or "9999") > day:
            continue
        until = c.get("active_until")
        if until and day > str(until):
            continue
        return c
    return None


def intensity_gate_active(constraint: dict[str, Any] | None, target_date: str) -> bool:
    """True when `constraint` still holds cardio to "no push" on `target_date` (#5076).

    False once the entry's `intensity_gate_retired_from` day has come: from then on the constraint
    shapes only the HR half (no HR tier, no HR target), and the menu's harder blocks are open."""
    if not constraint:
        return False
    retired = constraint.get("intensity_gate_retired_from")
    return not (retired and str(target_date or "")[:10] >= str(retired))


def stop_list_from(summary: Any, rule: int) -> str | None:
    """Rule `(rule)` of a numbered platform-memory note, verbatim, or None when the note has no such rule."""
    text = str(summary or "")
    m = re.search(rf"\({int(rule)}\)\s*(.+?)(?=\s*\({int(rule) + 1}\)|$)", text, re.DOTALL)
    return m.group(1).strip() if m else None


def talk_test_pick(pick: dict[str, Any], constraint: dict[str, Any] | None) -> dict[str, Any]:
    """`cardio_pick` under the constraint: the HR fields dropped, the talk-test cue written in their place."""
    if not constraint or constraint.get("hr_prescriptions_allowed", True):
        return pick
    out = {k: v for k, v in pick.items() if k not in HR_PICK_FIELDS}
    out["intensity"] = TALK_TEST_CUE
    out["hr_fields_dropped_by"] = constraint["id"]
    return out


def gate_cue(constraint: dict[str, Any]) -> str:
    """The one-line per-lift cue under the gate (replaces the band-keyed 🟢/🟡/🔴 line)."""
    g = constraint["gate"]
    return f"≤ RPE {g['sinus_rpe_cap']} (sinus rhythm) · ≤ RPE {g['not_sinus_rpe_cap']} (ECG not sinus, or feel off)"


def gate_lines(constraint: dict[str, Any], stop_list: str | None, green_withheld: str | None) -> list[str]:
    """The ECG + feel gate for the first exercise's notes, in place of the Whoop-band block.

    `stop_list` None (the memory row could not be read) is NAMED, never silently dropped."""
    g = constraint["gate"]
    since = constraint["active_from"]
    stop = stop_list or f"the stop list in platform memory ({since}) could not be read — re-read it before you train"
    lines = [
        f"— GATE: ECG + FEEL (Whoop bands invalid since {since}) —",
        "Take an ECG before you leave.",
        f"• Sinus rhythm + feel fine → the plan as written, every set ≤ RPE {g['sinus_rpe_cap']}.",
        f"• ECG not sinus, or feel off → every set ≤ RPE {g['not_sinus_rpe_cap']}; accessories and cardio optional.",
    ]
    if green_withheld:
        lines.append(f"• No 🟢 this week — {green_withheld}.")
    lines += [f"• Stop: {stop}", "Exhale through every press, no breath-hold. Get up slowly from the bench."]
    return lines
