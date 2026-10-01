"""content/story_ledger.py — the season ledger: what the series has told so far (#4533).

One row per published installment, ``LEDGER#{date}`` in the chronicle partition (already
phase-classified — no new partition), carrying exactly what the next installment needs to
pick the story up the way a human desk would:

  * ``threads`` — the running storylines, each ``open | advanced | resolved | retired`` with
    the week it opened, the week it last moved, and one line of where it stands;
  * ``bets`` — the Panel's on-air bet, with a rule code can grade, and its result once graded;
  * ``featured`` — which coach the week put in front of readers (rotation input);
  * ``leads`` / ``beats`` — the angle that led and the beats already used (repeat guard);
  * ``arcs`` — one line per character (Elena, each coach) on how they have moved.

Pure: the ledger is a dict in, a dict out. Persistence (`ledger_row` / `latest_visible`)
is the only part that touches a table, and it reads through ``singleton_visible`` so a
reset's tombstones can never become last week's memory (#4536: the Panel scored a July bet
from a tombstoned cycle-5 row).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

THREAD_STATUSES = ("open", "advanced", "resolved", "retired")
# A thread that has not moved in this many installments must be resolved or retired by name —
# the cure for both failure modes the 2026-10-01 review found: the beat that leads three weeks
# running, and the promise (score the predictions at two weeks) that silently never comes back.
STALE_AFTER = 3
MAX_CONSECUTIVE_LEAD = 2

LEDGER_PREFIX = "LEDGER#"


def empty_ledger() -> Dict[str, Any]:
    return {"week": None, "date": None, "threads": [], "bets": [], "featured": [], "leads": [], "beats": [], "arcs": {}, "titles": []}


def open_threads(ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in ledger.get("threads", []) if t.get("status") in ("open", "advanced")]


def stale_threads(ledger: Dict[str, Any], week: int) -> List[Dict[str, Any]]:
    """Open threads that have gone ``STALE_AFTER`` installments without moving."""

    def moved(t: Dict[str, Any]) -> int:
        for k in ("last_week", "opened_week"):  # week 0 (the prologue) is a real week — never treat it as "unset"
            if t.get(k) is not None:
                return int(t[k])
        return week

    return [t for t in open_threads(ledger) if week - moved(t) >= STALE_AFTER]


def last_open_bet(ledger: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    bets = [b for b in ledger.get("bets", []) if b.get("result") in (None, "", "open")]
    return bets[-1] if bets else None


def continuity_findings(prev: Dict[str, Any], budget: Dict[str, Any], week: int) -> List[str]:
    """What a budget must do with the season so far. Empty = it picks the story up properly.

    * every stale thread is resolved or retired by name;
    * every open thread is at least accounted for (advanced, resolved, retired, or held with a reason);
    * the lead does not run a third consecutive week on the same thread;
    * an open bet is scored."""
    findings: List[str] = []
    actions = {a.get("thread_id"): a for a in budget.get("thread_actions", []) if a.get("thread_id")}
    for t in stale_threads(prev, week):
        act = actions.get(t["id"], {}).get("action")
        if act not in ("resolve", "retire"):
            findings.append(
                f"stale thread {t['id']!r} ({t.get('title')}) has not moved in {STALE_AFTER} installments — resolve or retire it by name"
            )
    for t in open_threads(prev):
        if t["id"] not in actions:
            findings.append(f"open thread {t['id']!r} ({t.get('title')}) is not accounted for — advance, resolve, retire or hold it")
    lead_thread = (budget.get("lead") or {}).get("thread_id")
    recent = [entry.get("thread_id") for entry in prev.get("leads", [])[-MAX_CONSECUTIVE_LEAD:]]
    if lead_thread and len(recent) == MAX_CONSECUTIVE_LEAD and all(r == lead_thread for r in recent):
        findings.append(
            f"lead thread {lead_thread!r} has led {MAX_CONSECUTIVE_LEAD} weeks running — a third is a repeated beat; lead elsewhere"
        )
    if last_open_bet(prev) and (budget.get("bet_scored") or {}).get("result", "none") == "none":
        findings.append("last week's bet is open and the budget does not score it")
    return findings


def apply_budget(prev: Dict[str, Any], budget: Dict[str, Any], *, week: int, date: str, title: str) -> Dict[str, Any]:
    """The ledger after this installment publishes. Never mutates ``prev``."""
    led = copy.deepcopy(prev) if prev else empty_ledger()
    led["week"], led["date"] = week, date
    by_id = {t["id"]: t for t in led.get("threads", [])}
    for act in budget.get("thread_actions", []):
        tid, kind = act.get("thread_id"), act.get("action")
        if not tid:
            continue
        t = by_id.get(tid)
        if t is None:
            if kind != "open":
                continue
            t = {"id": tid, "title": act.get("title") or tid, "opened_week": week, "status": "open"}
            led.setdefault("threads", []).append(t)
            by_id[tid] = t
        status = {"open": "open", "advance": "advanced", "resolve": "resolved", "retire": "retired", "hold": t.get("status")}.get(kind)
        if status:
            t["status"] = status
        if kind != "hold":
            t["last_week"] = week
        if act.get("note"):
            t["note"] = act["note"]
    scored = budget.get("bet_scored") or {}
    if scored.get("result", "none") != "none":
        for b in reversed(led.get("bets", [])):
            if b.get("result") in (None, "", "open"):
                b["result"], b["scored_week"], b["verdict_note"] = scored.get("result"), week, scored.get("note")
                break
    if (budget.get("bet") or {}).get("claim"):
        led.setdefault("bets", []).append({**budget["bet"], "week": week, "result": "open"})
    lead = budget.get("lead") or {}
    led.setdefault("leads", []).append({"week": week, "thread_id": lead.get("thread_id"), "angle": lead.get("angle")})
    for coach in budget.get("featured_coaches", []):
        led.setdefault("featured", []).append({"week": week, "coach_id": coach})
    led.setdefault("beats", []).extend({"week": week, "beat": b} for b in budget.get("beats_used", []))
    for upd in budget.get("arc_updates") or []:
        if upd.get("who"):
            led.setdefault("arcs", {})[upd["who"]] = upd.get("line", "")
    led.setdefault("titles", []).append({"week": week, "date": date, "title": title})
    return led


def recently_featured(ledger: Dict[str, Any], n: int = 2) -> List[str]:
    return [f.get("coach_id") for f in ledger.get("featured", [])[-n:]]


def ledger_for_prompt(ledger: Dict[str, Any], week: int) -> Dict[str, Any]:
    """The slice a writer sees: open threads (with staleness flagged), the open bet, recent leads,
    beats already used, who was featured, the arcs, and the titles so far."""
    stale_ids = {t["id"] for t in stale_threads(ledger, week)}
    return {
        "previous_titles": ledger.get("titles", []),
        "open_threads": [{**t, "stale": t["id"] in stale_ids} for t in open_threads(ledger)],
        "closed_threads": [t for t in ledger.get("threads", []) if t.get("status") in ("resolved", "retired")][-6:],
        "open_bet": last_open_bet(ledger),
        "recent_leads": ledger.get("leads", [])[-3:],
        "beats_already_used": [b["beat"] for b in ledger.get("beats", [])][-14:],
        "recently_featured_coaches": recently_featured(ledger, 3),
        "character_arcs": ledger.get("arcs", {}),
    }


# ── persistence (the only I/O) ───────────────────────────────────────────────


def ledger_row(pk: str, ledger: Dict[str, Any], *, cycle: str, phase: str = "experiment") -> Dict[str, Any]:
    import json

    return {
        "pk": pk,
        "sk": f"{LEDGER_PREFIX}{ledger['date']}",
        "record_type": "story_ledger",
        "cycle": cycle,
        "phase": phase,
        "ledger_json": json.dumps(ledger),
    }


def latest_visible(table: Any, pk: str, before_date: str) -> Dict[str, Any]:
    """The newest ledger row strictly before ``before_date`` that the current phase can see."""
    import json

    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import singleton_visible

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(LEDGER_PREFIX, f"{LEDGER_PREFIX}{before_date}"), ScanIndexForward=False
    )
    for it in resp.get("Items", []):
        if it.get("sk") == f"{LEDGER_PREFIX}{before_date}" or not singleton_visible(it):
            continue
        try:
            return json.loads(it.get("ledger_json") or "{}") or empty_ledger()
        except ValueError:
            continue
    return empty_ledger()
