"""scripts/backlog_retirement.py — the two retirement-ledger rules `check_backlog_hygiene.py` runs (#5141).

Split out rather than added inline: `check_backlog_hygiene.py` sits 6 logical lines under
the module-size ceiling (#1665, measured 994/1000 on 2026-10-23), and the ceiling is paid by
extraction, never a baseline raise. The rules stay pure functions over the parsed corpus;
the hygiene linter wraps each returned tuple in its own `Finding` (no import back from it,
so there is no cycle). The grammar is `backlog_contract.retires_statement` — no regex here.

THE CONTRACT (issue #5141, platform build-and-cost review 2026-10-18)
  * `rule_retires_section` — a CHARTER story names what it retires. A charter story is an
    open type:story/bug/chore that `backlog_next.wave_of` places in a wave of
    `scripts/backlog_waves.json` (its own number, else its `**Epic:**` parent) — derived
    from the wave file, never a second list. It passes with a `## Retires` statement in its
    body (a named removal, or `none — <reason>` with a real reason) OR a row for it in
    `ledgers/retirement_ledger.py` (RETIREMENTS or ADDS_ONLY). Blocking for a story created
    on/after `RETIRES_EFFECTIVE_FROM`; one ADVISORY line naming every older one — the
    `SET_SECTION_EFFECTIVE_FROM` argument: an issue filed before the rule could not have
    stated a fact nobody asked for, and the advisory is the backfill worklist.
  * `rule_retirement_ledger_liveness` — the ledger's dead-man. A `planned` row whose story
    is not in the OPEN corpus is stale: the story closed (or was never open) and the ledger
    never recorded whether the removal shipped. Runs on the nightly wrap
    (`.github/workflows/wrap-nightly.yml`) and every /wrap (e7), so a closure that forgets
    the ledger reds within a day.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "ledgers" / "retirement_ledger.py"

# One day after the lane that added the rule opened (2026-10-23), so a story filed while
# the PR waits for review is named in the advisory, not retroactively redded.
RETIRES_EFFECTIVE_FROM = datetime(2026, 10, 25, tzinfo=timezone.utc)
# "none — tbd" is not a reason. Twenty characters is the shortest sentence that names a
# thing and a why ("adds a probe only").
RETIRES_REASON_MIN_CHARS = 20

WORK_TYPES = ("type:story", "type:bug", "type:chore")
VIOLATION, ADVISORY = "violation", "advisory"  # == check_backlog_hygiene.VIOLATION / ADVISORY (a test holds them equal)

Result = Tuple[str, Optional[int], str, str]  # (rule, issue number, message, severity) — a Finding's fields


def load_ledger(path: Optional[Path] = None) -> ModuleType:
    """`ledgers/retirement_ledger.py` as a module (ledgers/ is data, not a package)."""
    spec = importlib.util.spec_from_file_location("retirement_ledger", str(path or LEDGER_PATH))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ledger_stories(ledger: Any) -> set:
    """Every story number the ledger accounts for — a removal row or an adds-only row."""
    rows = list(getattr(ledger, "RETIREMENTS", {}).values()) + list(getattr(ledger, "ADDS_ONLY", {}).values())
    return {r.get("story") for r in rows if isinstance(r.get("story"), int)}


def is_charter_story(ctx: Dict[str, Any], waves: List[Dict[str, Any]]) -> bool:
    """An open work item the wave file places in a charter wave (number first, then epic parent)."""
    if not any(t in WORK_TYPES for t in ctx.get("types") or []):
        return False
    epic = ctx.get("epic_link")
    row = {"number": ctx.get("number"), "epic_parent": epic.number if epic else None}
    return bn.wave_of(row, waves) is not None


def _created(ctx: Dict[str, Any]) -> Optional[datetime]:
    stamp = ctx.get("created_at")
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def retires_problem(body: Optional[str]) -> Optional[str]:
    """Why a body's `## Retires` statement does not satisfy the contract, or None."""
    stated = bc.retires_statement(body)
    if stated is None:
        return "no `## Retires` statement — name what this charter story removes, or `none — <reason>` (#5141)"
    if stated.is_none and len(stated.reason or "") < RETIRES_REASON_MIN_CHARS:
        return f"`## Retires` says none with no real reason (`{stated.text}`) — the contract is `none — <reason>` (#5141)"
    return None


def rule_retires_section(ctxs: List[Dict[str, Any]], waves: List[Dict[str, Any]], ledger: Any) -> List[Result]:
    """Every charter story states what it retires (body or ledger row); see the module docstring."""
    covered = ledger_stories(ledger)
    out: List[Result] = []
    grandfathered: List[int] = []
    for ctx in ctxs:
        if not is_charter_story(ctx, waves) or ctx.get("number") in covered:
            continue
        problem = retires_problem(ctx.get("body"))
        if problem is None:
            continue
        created = _created(ctx)
        if created and created < RETIRES_EFFECTIVE_FROM:
            grandfathered.append(ctx["number"])
            continue
        out.append(("retires_section", ctx.get("number"), problem, VIOLATION))
    if grandfathered:
        out.append(
            (
                "retires_section",
                None,
                f"{len(grandfathered)} charter story(ies) filed before {RETIRES_EFFECTIVE_FROM.date()} name no retirement "
                f"(no `## Retires` line, no ledgers/retirement_ledger.py row): {sorted(grandfathered)} — grandfathered, "
                "named rather than silent; add the line or a ledger row (#5141)",
                ADVISORY,
            )
        )
    return out


def rule_retirement_ledger_liveness(ctxs: List[Dict[str, Any]], ledger: Any) -> List[Result]:
    """A `planned` ledger row whose story is not open is stale — the ledger's dead-man."""
    open_numbers = {c.get("number") for c in ctxs}
    out: List[Result] = []
    for key, row in sorted(getattr(ledger, "RETIREMENTS", {}).items()):
        story = row.get("story")
        if row.get("status") != "planned" or not isinstance(story, int) or story in open_numbers:
            continue
        out.append(
            (
                "retirement_ledger_liveness",
                story,
                f"ledgers/retirement_ledger.py row `{key}` is still `planned` but #{story} is not open — record whether "
                "the removal shipped (`retired` + pr + date) or was dropped (`kept` + reason) (#5141)",
                VIOLATION,
            )
        )
    return out


def run(ctxs: List[Dict[str, Any]], spec: Optional[Dict[str, Any]] = None, ledger: Any = None) -> List[Result]:
    """Both rules over the parsed open corpus; the wave file and ledger load from the repo by default."""
    spec = bn.load_waves() if spec is None else spec
    ledger = load_ledger() if ledger is None else ledger
    waves = list(spec.get("waves") or [])
    return rule_retires_section(ctxs, waves, ledger) + rule_retirement_ledger_liveness(ctxs, ledger)
