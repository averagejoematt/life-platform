"""content/story_ledger.py — the season ledger: what the series has told so far (#4533).

One row per published installment, ``LEDGER#{date}`` in the chronicle partition (already
phase-classified — no new partition), carrying exactly what the next installment needs to
pick the story up the way a human desk would:

  * ``threads`` — the running storylines, each ``open | advanced | resolved | retired`` with
    the week it opened, the week it last moved, and one line of where it stands;
  * ``bets`` — the Panel's on-air bet, with a rule code can grade, and its result once graded;
  * ``featured`` — which coach the week put in front of readers (rotation input);
  * ``leads`` / ``beats`` — the angle that led and the beats already used (repeat guard);
  * ``arcs`` — one line per character (Elena, each coach) on how they have moved;
  * ``asks`` — what a coach asked of him, ``open | followed_up | escalated`` (#4914).

THE ASK RULE (#4914) — one rule, ``matched_ask`` (scored by ``_match_score``), shared by the desk's validator and ``apply_budget``:
  * every ask carries a stable ``id`` (``ask_id`` of its normalized text), assigned when ``apply_budget``
    appends it; an ask already in the ledger WITHOUT an id gets the same deterministic id on read
    (``ask_key``), so no migration is needed;
  * a follow-up in the budget's ``asks_followed_up[]`` matches an ask when it cites that ``ask_id``, or —
    the fallback — quotes the ask's first ``ASK_PREFIX_CHARS`` normalized characters, or shares at least
    ``ASK_OVERLAP`` of its content words (and ``ASK_OVERLAP_MIN_WORDS`` of them) (a paraphrase is a follow-up);
  * outcome ``carried`` (``CARRIED``) means no reply and no data yet: the ask stays ``open`` with a
    ``carried_weeks`` count. After ``CARRIED_MAX_WEEKS`` carried installments it is ESCALATED — status
    ``escalated`` with ``escalated_week``, no longer demanded of the desk, listed by ``_escalated_asks`` (private until the reply desk, #4546, consumes it) for
    the reply desk (#4546) to put to him by email instead of asking the data something it cannot answer.

Pure: the ledger is a dict in, a dict out. Persistence (`ledger_row` / `latest_visible`)
is the only part that touches a table, and it reads through ``singleton_visible`` so a
reset's tombstones can never become last week's memory (#4536: the Panel scored a July bet
from a tombstoned cycle-5 row).
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Dict, List, Optional

THREAD_STATUSES = ("open", "advanced", "resolved", "retired")
# A thread that has not moved in this many installments must be resolved or retired by name —
# the cure for both failure modes the 2026-10-01 review found: the beat that leads three weeks
# running, and the promise (score the predictions at two weeks) that silently never comes back.
STALE_AFTER = 3
MAX_CONSECUTIVE_LEAD = 2
BET_CARRY_WEEKS = 2

LEDGER_PREFIX = "LEDGER#"

# ── the ask rule (#4914) ─────────────────────────────────────────────────────
CARRIED = "carried"  # an asks_followed_up outcome: no reply, no data yet
CARRIED_MAX_WEEKS = 3  # carried this many installments → escalated to the reply desk (#4546)
ASK_PREFIX_CHARS = 40  # the legacy verbatim rule, kept as one of the accepted ways to name an ask
ASK_OVERLAP = (
    0.4  # share of the FOLLOW-UP's own content words (4+ letters) that must be the ask's; the single best match wins, a tie matches nothing
)
ASK_OVERLAP_MIN_WORDS = 3  # ... and never fewer than this many shared words

_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: Any) -> str:
    return " ".join(_WORD.findall(str(text or "").lower()))


def _content_words(text: Any) -> set:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) >= 4}


def ask_id(text: Any) -> str:
    """The stable id of an ask: a short hash of its normalized text."""
    return "ask-" + hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:8]


def ask_key(ask: Dict[str, Any]) -> str:
    """The ask's id — the stored one, or the deterministic one for an ask the ledger holds without an id."""
    return str(ask.get("id") or ask_id(ask.get("ask")))


def _match_score(followup: Dict[str, Any], ask: Dict[str, Any]) -> float:
    """How strongly a follow-up names this ask: 3 = cites its id, 2 = quotes its opening, else the share of the
    FOLLOW-UP's content words that are this ask's (0 below the overlap floor)."""
    cited = str(followup.get("ask_id") or "").strip()
    if cited:
        return 3.0 if cited == ask_key(ask) else 0.0
    fu_text, ask_text = _norm(followup.get("ask")), _norm(ask.get("ask"))
    if not fu_text or not ask_text:
        return 0.0
    if ask_text[:ASK_PREFIX_CHARS] in fu_text:
        return 2.0
    f_words = _content_words(followup.get("ask"))
    shared = len(_content_words(ask.get("ask")) & f_words)
    if not f_words or shared < ASK_OVERLAP_MIN_WORDS:
        return 0.0
    ratio = shared / len(f_words)  # of what the follow-up SAYS, how much is this ask — a paraphrase compresses the ask, never the reverse
    return ratio if ratio >= ASK_OVERLAP else 0.0


def matched_ask(followup: Dict[str, Any], asks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The ONE ask a follow-up closes (#4914): the single best-scoring match, or None when nothing matches or the
    best is tied (ambiguous — a follow-up never closes two asks)."""
    scored = sorted(((_match_score(followup, a), i) for i, a in enumerate(asks) if a.get("ask")), reverse=True)
    if not scored or scored[0][0] <= 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return asks[scored[0][1]]


def is_carried(outcome: Any) -> bool:
    """``carried`` — alone or elaborated (``carried — no reply yet``) — means no reply and no data."""
    return _norm(outcome).split()[:1] == [CARRIED]


def is_open_ask(ask: Dict[str, Any]) -> bool:
    return ask.get("status") in (None, "", "open")


def open_asks(ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [a for a in ledger.get("asks", []) if is_open_ask(a)]


def _escalated_asks(ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Asks carried ``CARRIED_MAX_WEEKS`` installments with no reply — for the reply desk (#4546) to put to him."""
    return [a for a in ledger.get("asks", []) if a.get("status") == "escalated"]


def unfollowed_asks(ledger: Dict[str, Any], budget: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Open asks no entry of the budget's ``asks_followed_up`` matches."""
    opens = [a for a in open_asks(ledger) if a.get("ask")]
    claimed = {id(matched_ask(fu, opens)) for fu in budget.get("asks_followed_up") or []}
    return [a for a in opens if id(a) not in claimed]


def empty_ledger() -> Dict[str, Any]:
    return {
        "week": None,
        "date": None,
        "threads": [],
        "bets": [],
        "featured": [],
        "leads": [],
        "beats": [],
        "arcs": {},
        "titles": [],
        "asks": [],
        "spine": {},
    }


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
    scored_weeks = {s.get("bet_week") for s in budget.get("bets_scored") or []}
    for b in prev.get("bets", []):
        if (
            b.get("result") in (None, "", "open")
            and b.get("week") is not None
            and week - int(b["week"]) >= 2
            and b["week"] not in scored_weeks
        ):
            findings.append(
                f"the Week {b['week']} bet ({str(b.get('claim'))[:60]}…) is still open after its window — score it in bets_scored"
            )
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
                # A bet whose window has not closed yet is CARRIED, not dropped (#4533: Ep0's Day-7 weight bet fell
                # into Ep1's 3-day window, was marked not_gradable and vanished — it had won). It expires only
                # after BET_CARRY_WEEKS installments.
                if scored.get("result") == "not_gradable" and week - int(b.get("week") or week) < BET_CARRY_WEEKS:
                    b["carried_note"] = scored.get("note")
                    break
                b["result"], b["scored_week"], b["verdict_note"] = scored.get("result"), week, scored.get("note")
                break
    for sc in budget.get("bets_scored") or []:  # every open bet whose window closed, carried ones included
        for b in led.get("bets", []):
            if b.get("week") == sc.get("bet_week") and b.get("result") in (None, "", "open") and sc.get("result") != "not_gradable":
                b["result"], b["scored_week"], b["verdict_note"], b["winner"] = sc["result"], week, sc.get("note"), sc.get("winner")
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
    if not led.get("spine"):
        from content.story_craft import season_spine

        led["spine"] = season_spine()
    for fu in budget.get("asks_followed_up", []):
        a = matched_ask(fu, [x for x in led.setdefault("asks", []) if is_open_ask(x) and x.get("ask")])
        if a is None:
            continue
        a.setdefault("id", ask_key(a))
        if is_carried(fu.get("outcome")):
            a["carried_weeks"] = int(a.get("carried_weeks") or 0) + 1
            if a["carried_weeks"] >= CARRIED_MAX_WEEKS:
                a["status"], a["escalated_week"] = "escalated", week
        else:
            a["status"], a["outcome"], a["followed_week"] = "followed_up", fu.get("outcome"), week
    for ask in budget.get("coach_asks", []):
        if ask.get("ask"):
            led.setdefault("asks", []).append({**ask, "id": ask_id(ask["ask"]), "week": week, "status": "open"})
    if budget.get("throughline_advanced"):
        led.setdefault("throughline_log", []).append({"week": week, "id": budget["throughline_advanced"]})
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
        "season_spine": ledger.get("spine") or {},
        "open_coach_asks": [{**a, "id": ask_key(a)} for a in open_asks(ledger)],
        "throughline_log": ledger.get("throughline_log", [])[-4:],
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


_UNSET: Any = object()


def current_cycle() -> Optional[str]:
    """The cycle this experiment is — the one whose genesis is ``EXPERIMENT_START_DATE`` in the
    CYCLE_GENESES registry (the same registry the write-time stamp derives ``cycle`` from, #3598).

    Keyed on the genesis rather than today's date, so the countdown between a reset and its genesis
    already names the NEW cycle. ``None`` when the registry cannot be read: the caller then falls
    back to the tombstone/phase filter alone — an unknown cycle is reported, never invented."""
    try:
        from common.constants import EXPERIMENT_START_DATE
        from experiment.phase_taxonomy import _cycle_geneses, cycle_for_date

        n = cycle_for_date(EXPERIMENT_START_DATE, _cycle_geneses())
        return None if n is None else str(n)
    except Exception:  # noqa: BLE001 — a read helper never raises into the desk
        return None


def row_visible(item: Optional[Dict[str, Any]], cycle: Optional[str]) -> bool:
    """Whether a ``LEDGER#`` row is this cycle's season memory (#4533).

    Two independent conditions, both required:
      * ``singleton_visible`` — not tombstoned by a reset, and phase is the current phase;
      * the row's ``cycle`` is ``cycle`` — a ledger is one season's memory, so a row a previous
        cycle left behind (one the reset's wipe missed, or a row re-tagged ``experiment`` by hand)
        must never become last week's threads and bets. A row with NO cycle cannot prove it
        belongs to this season and is hidden too. ``cycle=None`` (registry unreadable) skips only
        this second condition.

    The cycle compares as a string: the publish path writes ``"17"`` and the write-time stamp
    overwrites it with the number 17 (a DynamoDB ``N`` → ``Decimal('17')``); both are this cycle."""
    from experiment.phase_filter import singleton_visible

    if not singleton_visible(item):
        return False
    if cycle is None:
        return True
    raw = (item or {}).get("cycle")
    return raw is not None and str(raw).strip() == str(cycle).strip()


def latest_visible(table: Any, pk: str, before_date: str, *, cycle: Any = _UNSET) -> Dict[str, Any]:
    """The newest ledger row strictly before ``before_date`` that THIS cycle's season can see.

    The ONE read door for the season memory: the chronicle desk, the Panel episode written with it
    (``story_pipeline.live_week``) and the Monday questions all read through here, so a tombstoned or
    previous-cycle row is invisible to every writer at once. ``cycle`` defaults to ``current_cycle()``."""
    import json

    from boto3.dynamodb.conditions import Key

    if cycle is _UNSET:
        cycle = current_cycle()
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(LEDGER_PREFIX, f"{LEDGER_PREFIX}{before_date}"), ScanIndexForward=False
    )
    for it in resp.get("Items", []):
        if it.get("sk") == f"{LEDGER_PREFIX}{before_date}" or not row_visible(it, cycle):
            continue
        try:
            return json.loads(it.get("ledger_json") or "{}") or empty_ledger()
        except ValueError:
            continue
    return empty_ledger()
