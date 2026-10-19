"""training/green_block.py — the v0.5 session set ceiling and the 🟢 bonus block (#4503, OD4 + OD5 + OD8a).

Owner rulings, adopted 2026-09-30 (Session BB, the v0.5 red team):

  * OD4 (A): base 60–75 hard sets/wk; 🟢 adds at most +4 sets per upper session and +3 per lower
    session, at most +12 a week; the session ceiling goes from 18 to 20 for the base and 24 with 🟢.
  * OD5 (A): `protein_floor_missed` blocks the 🟢 block ONLY. It no longer stops gains or the base
    sets (the gain rule itself lives in `owner_redlines.REDLINES['lifting_sessions_per_wk']['gain_rule']`).
  * OD8 (a): no 🟢 tail on the v0.4 templates while they were LOCKED. The lock clause is gone — owner
    ruling 6 (2026-10-18, #5069) lifted the v0.4 lock (history: `program_v04.BLOCK_LOCK`). What remains is
    a fact, not a rule: no template carries a `bonus` exposure today, so raising the ceiling adds no set to
    any session — the ceiling is a BOUND the generator trims to, never a target it fills.

The IR's `bonus` role is the exposure kind `BONUS_KIND`. `full_body_session` tags each block
`{kind}:{pattern}:{intensity}`, so a 🟢 block is any block whose `rationale_tag` starts with `bonus:`.
`session_set_check` is the one place a drafted session is graded against these numbers.
"""

from __future__ import annotations

from typing import Any

BASE_SESSION_SET_CEILING = 20
GREEN_SESSION_SET_CEILING = 24
GREEN_BONUS_SETS_PER_SESSION = {"upper": 4, "lower": 3}
GREEN_BONUS_SETS_PER_WEEK = 12
BONUS_KIND = "bonus"
GREEN_BLOCKED_BY = ("protein_floor_missed",)
# The per-session lines `owner_redlines`' `volume_ceiling` tripwire reports — read from here so it cannot keep v0.4's 18.
SESSION_SET_CEILINGS = {"sets_per_session": BASE_SESSION_SET_CEILING, "sets_per_session_with_green": GREEN_SESSION_SET_CEILING}

PROVENANCE = {
    "provenance": "owner",
    "stated": "2026-09-30",
    "ref": "#4503 — OD4 (A) ceiling 18 -> 20 base / 24 with 🟢, 🟢 <= +4 upper / +3 lower per session, <= +12/wk; "
    "OD5 (A) protein_floor_missed gates the 🟢 block only; OD8 (a)'s lock clause lifted by owner ruling 6 (2026-10-18, #5069)",
}


def _is_bonus(block: Any) -> bool:
    return str(getattr(block, "rationale_tag", "") or "").split(":")[0] == BONUS_KIND


def session_set_check(blocks: list[Any], archetype: str | None = None) -> list[str]:
    """Warnings for a drafted session against the v0.5 ceilings (empty when it fits). The base sets
    (every non-`bonus` block) are graded against 20; the 🟢 sets against the per-session cap for the
    archetype; the two together against 24."""
    from training.warmup_sets import working_set_count  # #5049: a warm-up is not a hard set

    base = sum(working_set_count(getattr(b, "sets", None)) for b in blocks if not _is_bonus(b))
    bonus = sum(working_set_count(getattr(b, "sets", None)) for b in blocks if _is_bonus(b))
    out: list[str] = []
    if base > BASE_SESSION_SET_CEILING:
        out.append(
            f"base sets {base} exceed the session ceiling {BASE_SESSION_SET_CEILING} (OD4; 🟢 sets are counted separately, up to {GREEN_SESSION_SET_CEILING})"
        )
    cap = GREEN_BONUS_SETS_PER_SESSION.get(str(archetype or "").lower())
    if bonus and cap is not None and bonus > cap:
        out.append(f"🟢 sets {bonus} exceed the {archetype} session's +{cap} (OD4)")
    if base + bonus > GREEN_SESSION_SET_CEILING:
        out.append(f"total sets {base + bonus} exceed the 🟢 session ceiling {GREEN_SESSION_SET_CEILING} (OD4)")
    return out
