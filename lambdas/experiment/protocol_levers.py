"""lambdas/experiment/protocol_levers.py — the PROTOCOL# write contract (#3621 box 5).

THE CLAUSE THIS MAKES GRADEABLE
───────────────────────────────
The quantified-self anchor says "every protocol lever states the data it targets and the
hypothesis that spawned it". Measured 2026-09-06 that clause passed VACUOUSLY: the live
`/api/protocols` returned `count=0`, the DDB query returned 0 items, and the 24-key
schema had no hypothesis-linkage field at all. A clause graded against an empty set is
not a clause — every reviewer who will ever occupy a grading moment sees a pass.

Re-measured 2026-09-20 (read-only query of `USER#matthew#SOURCE#protocols`): NINE
`PROTOCOL#` rows exist — cgm, intermittent_fasting, morning_sunlight, post_meal_walks,
sleep, strength, supplement_repletion_2026_05, weekly_in_person_conversation, zone2 —
and every one of them is `tombstone=true, cycle=5, phase=pilot,
tombstoned_reason=experiment_restart_2026-07-13`. So the endpoint's `count=0` is the
phase filter doing its job over an archive, not an empty table, and NOT ONE of the nine
carries a `spawned_by`. Those nine are DELIBERATELY not re-put: a tombstoned row's
generation identity is the record that cycle 5 happened (#1202/ADR-077, and the #3621
box-1 ruling that re-putting 329 reason strings would destroy the record). The contract
below therefore binds the NEXT write, which is the only honest place to bind it.

THE FIELD
─────────
`spawned_by` is either
  * a `HYPOTHESIS#…` id — the sk of the row on `USER#matthew#SOURCE#hypotheses` that this
    lever came out of (`hypothesis_engine_lambda` writes `HYPOTHESIS#<ISO-timestamp>`), or
  * the exact label `pre-platform / literature` — the explicit admission that NO platform
    hypothesis spawned this lever: it predates the hypothesis engine.

There is no third value and no empty one, and the label is not a claim about WHY the
lever exists — `origin` already carries that prose, and it varies ("Published literature
(Walker, 2017…)", "N=1 experiment (Week 3 — proved out)", "Personal conviction — glucose
anxiety → data as resolution"). `origin` is not a linkage, cannot be resolved, and is
deliberately left alone rather than overloaded: a field that sometimes means "a paper"
and sometimes means "row 2026-09-14T19:00:00+00:00" is a field a reader cannot grade.
`spawned_by` answers exactly one question — WHICH hypothesis, or none — and the two
fields are read together.

WHY THE REFUSAL IS AT THE WRITE AND NOT AT THE READ
───────────────────────────────────────────────────
A read-side filter would hide an unlinked lever, which reads to the site exactly like a
lever that does not exist — the vacuity this issue is about, rebuilt one layer down. The
refusal is at the write so an unlinked lever never enters the table, and the catalogue
audit is the same predicate over the file the site serves, so neither door is the only
one guarded.

THE PHASE CLASS IS SETTLED AND NOT RE-OPENED HERE
─────────────────────────────────────────────────
Owner ruling 2026-09-05 (#3606 item 8): protocol levers STAY `experiment_scoped` and are
wiped with the cycle — "a reset should be brute force". `phase_taxonomy.SOURCE_CLASS`
already says so and `restart_intelligence_wipe.PARTITIONS` already covers `protocols` in
`"all"` mode. Nothing in this module changes that, and the write contract is a
within-a-cycle contract exactly as the ruling scopes it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

#: The sanctioned label for a lever that did NOT come out of a platform hypothesis. Exact
#: string, not a prefix and not a case-insensitive match: an unbounded free-text escape
#: hatch is the `origin` field this exists to replace.
PRE_PLATFORM = "pre-platform / literature"

#: The other admissible shape — the sk of a row on the hypotheses partition.
HYPOTHESIS_SK = re.compile(r"^HYPOTHESIS#\S.*$")

#: The DDB partition levers live on, and the sk prefix. Named here so the writer and the
#: seeder cannot drift on where a lever goes.
PROTOCOLS_SOURCE = "protocols"
PROTOCOL_SK_PREFIX = "PROTOCOL#"


class ProtocolLeverRefused(ValueError):
    """A PROTOCOL# write whose `spawned_by` is absent, empty or unrecognised. Raised at
    the write — never downgraded to a warning, never fixed up with a default value. A
    default would make every lever claim a provenance nobody chose."""


def spawned_by_problem(value: Any) -> str | None:
    """The reason `value` is not an admissible `spawned_by`, or None when it is. PURE.

    Separated from the refusal so a caller can report WHY rather than only THAT — and so
    the catalogue audit and the DDB writer grade with one predicate instead of two.
    """
    if value is None:
        return "absent — every lever must name the hypothesis that spawned it, or say plainly that none did"
    if not isinstance(value, str):
        return f"is a {type(value).__name__}, not a string"
    stripped = value.strip()
    if not stripped:
        return "is empty/whitespace, which states nothing"
    if stripped == PRE_PLATFORM:
        return None
    if HYPOTHESIS_SK.match(stripped):
        return None
    if stripped.lower() == PRE_PLATFORM.lower() or stripped.lower().startswith("pre-platform"):
        return f"is {stripped!r} — the literature label is the EXACT string {PRE_PLATFORM!r} (spelling is the contract)"
    return (
        f"is {stripped!r} — not a HYPOTHESIS# id and not the literal {PRE_PLATFORM!r}. A prose citation belongs in "
        "`origin`; `spawned_by` is a linkage a reader can follow or an explicit admission that there is none"
    )


def require_spawned_by(protocol: dict, *, where: str = "protocol") -> str:
    """THE REFUSAL. Returns the validated `spawned_by`, or raises ProtocolLeverRefused."""
    problem = spawned_by_problem((protocol or {}).get("spawned_by"))
    if problem is not None:
        pid = (protocol or {}).get("id") or "<no id>"
        raise ProtocolLeverRefused(
            f"{where} {pid!r}: `spawned_by` {problem}. A protocol lever is a falsifiable bet; the platform "
            f"publishes it as one. Set it to the HYPOTHESIS# id the lever came from, or to {PRE_PLATFORM!r} "
            "if it predates the platform's own evidence (#3621)."
        )
    return str(protocol["spawned_by"]).strip()


def build_protocol_item(protocol: dict, *, pk: str) -> dict:
    """THE DDB WRITE CHOKEPOINT — a validated `PROTOCOL#` item, or a refusal.

    Every `put_item` onto the protocols partition goes through here (today: the seeder,
    `deploy/seed_protocols.py`). It refuses before it builds, so a caller cannot get a
    half-formed item back and write it anyway. Returns a plain dict — Decimal conversion
    is the caller's job, per the repo's `Decimal` convention, and doing it here would hide
    the float from the caller who owns the boto3 client.
    """
    if not isinstance(protocol, dict):
        raise ProtocolLeverRefused(f"protocol payload is a {type(protocol).__name__}, not a dict")
    pid = protocol.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ProtocolLeverRefused("protocol payload has no `id` — a lever with no id has no sk and no page")
    require_spawned_by(protocol, where="protocol")
    item = dict(protocol)
    item["pk"] = pk
    item["sk"] = f"{PROTOCOL_SK_PREFIX}{pid.strip()}"
    return item


def audit_catalog(protocols: Iterable[dict]) -> list[str]:
    """THE BATCH VERDICT — the same predicate over a whole catalogue. Returns one line per
    offender; an empty list means every lever is linked.

    Called by `deploy/seed_protocols.py::build_items` before a single item is built (so a
    seed reports EVERY offender at once instead of stopping at the first), and by the
    contract test over `site/config/protocols.json` — the file `/api/protocols` falls back
    to when the DDB query fails. One predicate, both doors.

    Vacuity is a finding here, not a pass: an empty catalogue returns a finding rather
    than `[]`, because "no lever is unlinked" over zero levers is exactly the vacuous
    grade this whole box exists to end.
    """
    rows = list(protocols or [])
    if not rows:
        return ["the protocol catalogue is EMPTY — the lever clause cannot be graded against zero levers (#3621)"]
    problems: list[str] = []
    for i, p in enumerate(rows):
        pid = (p or {}).get("id") or f"[{i}]"
        problem = spawned_by_problem((p or {}).get("spawned_by"))
        if problem is not None:
            problems.append(f"{pid}: `spawned_by` {problem}")
    return problems
