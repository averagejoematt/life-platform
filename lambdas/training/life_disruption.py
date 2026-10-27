"""life_disruption.py — the whole-day life-disruption playbook and the 72-hour lapse protocol (#5122, epic #5120).

THE DEFECT. Disruption mode (#5088, ``training.disruption``) covered training only: on a bad stretch the habits, the
targets, the grading and the streak language still ran at full strictness, so one bad week read as a string of
misses — the streak-shaming spiral ``config/user_goals.json`` ``failure_mode`` describes ("the enemy is total
shutdown, not a bad week").

THE PLAYBOOK IS DATA. ``config/training_charter.json`` ``disruption`` carries it: two whole-day templates beside
travel and busy (``life``, up to its own ``max_days``; ``lapse``, ``lapse_protocol.hours`` long), ``whole_day`` (the
held and paused core habits, the paused targets, the no-grading rule, the streak-language rule) and
``lapse_protocol`` (what runs, what pauses, the trigger, the resume). This module reads it; it restates no number.

THE SWITCH IS HIS. Entering and leaving is ONE owner action on the #5088 path — ``get_exercise_notes
action='disruption'`` with ``template='life'|'lapse'`` and his words verbatim, ``action='disruption_end'`` to leave —
and the record (``training.disruption.DISRUPTION_STORE``, Tier 2 owner-only) is the log: start, until, template,
words, ``recorded_at``, and on leaving ``ended_on`` / ``end_words`` / ``ended_recorded_at``. The MCP audit trail
classes that tool a write (``mcp/audit.py::WRITE_TOOLS_BEHIND_READ_VERB``).

THE TRIGGER IS THE EARLY-WARNING FLAG. The lapse protocol is OFFERED, never applied, when the relapse early-warning
flag (#5121, ``health.early_warning``: ``USER#matthew#SOURCE#early_warning_flag`` / ``DATE#<day>``, owner-only) has an
active episode — the newest row ``active``, the episode starting at the first of the unbroken run of active rows
before it. The offer is routed through the ONE response owner (``failure_mode.response_owner``,
``coach.response_protocol``). This module reads the flag only through ``health.early_warning.read_recent``; until
#5121 is on main that import fails and the flag state is ``not_wired`` (stated, never guessed). ``flag_episode`` reads
the same row contract as ``early_warning.episode`` (parity-tested when the module is importable).

OWNER-ONLY. ``mode`` and ``lines`` are owner-channel material (the coach context with ``published=False``, the
owner's own Telegram threads). The ONE published-side read is ``published_language_line``: the language rule alone,
naming no mode, no record, no reason and no flag, and it reads the disruption record only — never the flag (no
email, web or content module reads the flag, #5121).

PURE except ``current`` / ``read_flag_rows`` / ``records_failsoft`` (fail-soft I/O).
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Iterable, Optional

from common.pacific_time import shift_day_key

logger = logging.getLogger(__name__)

ISSUE = "#5122"
VERSION = "life-disruption@1.0.0"
SOURCE = "config/training_charter.json disruption.whole_day + disruption.lapse_protocol (training.life_disruption)"
FLAG_SOURCE = "early_warning_flag (health.early_warning, #5121)"
FLAG_READER = "health.early_warning"  # the one reader of the flag partition (#5121); this module never spells its key

SCOPE_OFF, SCOPE_TRAINING, SCOPE_WHOLE_DAY = "off", "training", "whole_day"
FLAG_ACTIVE, FLAG_CLEAR, FLAG_ABSENT, FLAG_NOT_WIRED = "active", "clear", "absent", "not_wired"


# ── the charter reads ───────────────────────────────────────────────────────────────────────
def _policy() -> dict[str, Any]:
    from training import disruption  # noqa: PLC0415

    return disruption.policy()


def playbook() -> dict[str, Any]:
    """The charter's ``disruption.whole_day`` block, as read ({} when absent)."""
    return dict(_policy().get("whole_day") or {})


def lapse_protocol() -> dict[str, Any]:
    """The charter's ``disruption.lapse_protocol`` block, as read ({} when absent)."""
    return dict(_policy().get("lapse_protocol") or {})


def template(name: Optional[str]) -> dict[str, Any]:
    return dict((_policy().get("templates") or {}).get(name or "") or {})


def is_whole_day(name: Optional[str]) -> bool:
    return bool(template(name).get("whole_day"))


def whole_day_templates() -> list[str]:
    return sorted(k for k, v in (_policy().get("templates") or {}).items() if (v or {}).get("whole_day"))


def core_ids() -> list[str]:
    from training.training_charter import charter_value  # noqa: PLC0415

    return [str(e.get("id")) for e in (charter_value("habits.core", []) or []) if isinstance(e, dict) and e.get("id")]


def habit_problems() -> list[str]:
    """Every breach of ``whole_day.habits_rule``: each core id held or paused, never both, never neither, none unknown."""
    pb = playbook()
    held, paused, core = set(pb.get("held_habits") or []), set(pb.get("paused_habits") or []), set(core_ids())
    out = [f"{h}: both held and paused" for h in sorted(held & paused)]
    out += [f"{h}: neither held nor paused" for h in sorted(core - held - paused)]
    out += [f"{h}: not a habits.core id" for h in sorted((held | paused) - core)]
    return out


# ── the language rule ─────────────────────────────────────────────────────────────────────
def language() -> dict[str, Any]:
    return dict(playbook().get("language") or {})


def patterns() -> list[re.Pattern]:
    """The charter's ``language.never`` patterns, compiled case-insensitively (a pattern that will not compile is
    logged and skipped, never silently matched as nothing — the count is checked by the test)."""
    out = []
    for p in language().get("never") or []:
        try:
            out.append(re.compile(str(p), re.IGNORECASE))
        except re.error as e:
            logger.warning("[life_disruption] language pattern %r does not compile: %s", p, e)
    return out


def shaming(text: Any) -> list[str]:
    """Every streak-shaming phrase in ``text`` (the matched spans, in order). Empty = clean."""
    s = str(text or "")
    return [m.group(0) for p in patterns() for m in p.finditer(s)]


def published_language_line(records: Optional[list[dict[str, Any]]], days: Iterable[str]) -> str:
    """The daily coaches' language line (#5122) when a whole-day template covers any of ``days``, else "".

    Published-safe by construction: it states the rule and the charter's ``instead``, and names no mode, record,
    template, date, reason or flag (the brief's TL;DR reaches the site). Reads the disruption record only."""
    from training import disruption  # noqa: PLC0415

    whole = set(whole_day_templates())
    covered = any((disruption.active_record(records, d) or {}).get("template") in whole for d in days)
    lang = language()
    if not covered or not lang.get("instead"):
        return ""
    return (
        "- Language today (charter disruption.whole_day.language): count no broken streak and shame no miss; "
        f"{lang['instead']}. A held habit with no reading is unknown, never a miss"
    )


# ── the early-warning flag (#5121's row contract) ─────────────────────────────────────────
def _row_day(row: dict[str, Any]) -> Optional[str]:
    d = str(row.get("date") or str(row.get("sk") or "")[len("DATE#") :])[:10]
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else None


def flag_episode(rows: Optional[list[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    """The current episode when the newest row is active: ``{start, latest, markers, evidence}``, else None. A day
    with no row does not end an episode; an explicit inactive row does (``health.early_warning.episode``'s contract)."""
    ordered = sorted((r for r in rows or [] if _row_day(r)), key=_row_day)
    if not ordered or not ordered[-1].get("active"):
        return None
    start = _row_day(ordered[-1])
    for r in reversed(ordered[:-1]):
        if not r.get("active"):
            break
        start = _row_day(r)
    newest = ordered[-1]
    ev = newest.get("evidence") or {}
    return {
        "start": start,
        "latest": _row_day(newest),
        "markers": list(newest.get("markers") or []),
        "evidence": [str(ev.get(m) or m) for m in newest.get("markers") or []],
    }


def flag_view(rows: Optional[list[dict[str, Any]]], day: str, fresh_days: int = 2) -> dict[str, Any]:
    """``{state, since, latest, evidence}``: rows None = not_wired (no reader on main yet); no fresh row = absent."""
    if rows is None:
        return {"state": FLAG_NOT_WIRED, "source": FLAG_SOURCE, "detail": "health.early_warning is not importable (#5121 not merged)"}
    dated = sorted(d for d in (_row_day(r) for r in rows) if d)
    if not dated or dated[-1] < shift_day_key(day, -fresh_days):
        return {"state": FLAG_ABSENT, "source": FLAG_SOURCE, "detail": f"no flag reading in the {fresh_days} days before {day}"}
    ep = flag_episode(rows)
    if ep is None:
        return {"state": FLAG_CLEAR, "source": FLAG_SOURCE, "latest": dated[-1]}
    return {"state": FLAG_ACTIVE, "source": FLAG_SOURCE, "since": ep["start"], "latest": ep["latest"], "evidence": ep["evidence"]}


# ── the mode for a day ────────────────────────────────────────────────────────────────────
def _resumes_on(st: dict[str, Any]) -> Optional[str]:
    """The first day of the full plan: the morning after the last covered day (lapse: no step-back-up week)."""
    last = st.get("step_back_up_through") or st.get("until")
    return shift_day_key(str(last)[:10], 1) if last else None


def _offer(flag: dict[str, Any], response: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if flag.get("state") != FLAG_ACTIVE:
        return None
    lp = lapse_protocol()
    owner = (response or {}).get("owner")
    return {
        "offered": True,
        "applies": False,
        "template": "lapse",
        "hours": lp.get("hours"),
        "since": flag.get("since"),
        "signals": list(flag.get("evidence") or []),
        "owner": owner,
        "owner_name": (response or {}).get("owner_name") or owner or "unassigned",
        "owner_ref": lp.get("owner_ref"),
        "how": lp.get("entered_by"),
    }


def mode(
    records: Optional[list[dict[str, Any]]],
    day: str,
    *,
    flag_rows: Optional[list[dict[str, Any]]] = None,
    response: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The whole-day mode for ``day`` (owner channel): scope off | training | whole_day, what is held and paused,
    when the plan resumes, the early-warning flag's state and the lapse offer it raises. ``lines`` is the text form."""
    from training import disruption  # noqa: PLC0415

    st = disruption.state(records, day)
    active = st.get("phase") == disruption.PHASE_ACTIVE
    whole = active and is_whole_day(st.get("template"))
    scope = SCOPE_WHOLE_DAY if whole else (SCOPE_TRAINING if st.get("phase") != disruption.PHASE_OFF else SCOPE_OFF)
    pb, lp = playbook(), lapse_protocol()
    tmpl = template(st.get("template"))
    flag = flag_view(flag_rows, day)
    out: dict[str, Any] = {
        "source": SOURCE,
        "version": VERSION,
        "day": day,
        "scope": scope,
        "phase": st.get("phase"),
        "template": st.get("template"),
        "start_date": st.get("start_date"),
        "until": st.get("until"),
        "resumes_on": _resumes_on(st) if scope != SCOPE_OFF else None,
        "lapse": bool(whole and tmpl.get("lapse")),
        "owes_step_back_up": bool(st.get("owes_step_back_up")),
        "held_habits": list(pb.get("held_habits") or []) if whole else None,
        "paused_habits": list(pb.get("paused_habits") or []) if whole else None,
        "paused_targets": list(pb.get("paused_targets") or []) if whole else None,
        "grading_paused": list((pb.get("grading") or {}).get("paused") or []) if whole else None,
        "language_on": whole,
        "playbook_problems": habit_problems() if whole else None,  # a mis-specified held/paused split is stated, never hidden
        "runs": list(lp.get("runs") or []) if whole and tmpl.get("lapse") else None,
        "flag": flag,
        "lapse_offer": None if whole else _offer(flag, response),
    }
    out["lines"] = lines(out)
    out["language_violations"] = shaming("\n".join(out["lines"]))  # its own text held to its own rule; [] = clean
    return out


def lines(m: dict[str, Any]) -> list[str]:
    """The owner-channel text of ``mode``: [] when the day is off and nothing is offered."""
    pb, lp = playbook(), lapse_protocol()
    out: list[str] = []
    if m.get("scope") == SCOPE_WHOLE_DAY:
        kind = f"the {lp.get('hours')}-hour lapse protocol" if m.get("lapse") else "a life disruption"
        out.append(
            f"Whole-day disruption mode is ON ({m.get('template')}: {kind}), {m.get('start_date')} through {m.get('until')}, "
            f"on his own word; the day's targets and grading resume {m.get('resumes_on')}"
            + (
                ", the training stepping back up first (disruption.step_back_up)."
                if m.get("owes_step_back_up")
                else " with the full plan (no step-back-up week)."
            )
        )
        out.append(
            "Held (still asked for): "
            + ", ".join(m.get("held_habits") or [])
            + ". Paused (not asked for, never a miss): "
            + ", ".join(m.get("paused_habits") or [])
            + "."
        )
        out.append("Targets paused: " + ", ".join(m.get("paused_targets") or []) + f". {pb.get('targets_rule') or ''}".rstrip())
        out.append("Grading paused: " + ", ".join(m.get("grading_paused") or []) + f" — {(pb.get('grading') or {}).get('rule') or ''}.")
        if m.get("runs"):
            out.append("What runs: " + "; ".join(m["runs"]) + f". Resumes: {lp.get('resumes')}.")
        out.append(f"Language: {language().get('rule')}; {language().get('instead')}.")
        out += [f"Playbook problem (charter disruption.whole_day): {p}" for p in m.get("playbook_problems") or []]
    elif m.get("scope") == SCOPE_TRAINING:
        out.append(
            f"Training disruption mode ({m.get('template')}, {m.get('phase')}) through {m.get('until')}: the training is held; "
            "the rest of the day runs at the plan's own targets (no whole-day template is on)."
        )
    offer = m.get("lapse_offer")
    if offer:
        out.append(
            f"The relapse early-warning flag is ACTIVE since {offer.get('since')} ({len(offer.get('signals') or [])} signal(s)). "
            f"{offer.get('owner_name')} ({offer.get('owner') or 'unassigned'}) OFFERS the {offer.get('hours')}-hour lapse protocol "
            f"once, in the owner's own channel, and never applies it; it starts only on {offer.get('how')}. "
            "Every other coach holds its domain to that and adds no second ask."
        )
    return out


def owner_lines(m: dict[str, Any], persona: Optional[str]) -> list[str]:
    """``lines`` for one coach's own thread: the response owner is told the offer is theirs to make."""
    out = list(m.get("lines") or [])
    offer = m.get("lapse_offer")
    if offer and persona and persona == offer.get("owner"):
        out.append("You own this response (failure_mode.response_owner): make the one offer, with empathy, and nothing else today.")
    return out


# ── I/O (fail-soft) ───────────────────────────────────────────────────────────────────────
def read_flag_rows(table: Any, day: str) -> Optional[list[dict[str, Any]]]:
    """The flag rows through ``health.early_warning.read_recent``; None when that reader is not on main (#5121)."""
    try:  # by name: the module is #5121's and is not on main until it merges (a static import would not type-check)
        early_warning = importlib.import_module(FLAG_READER)
    except ImportError:
        return None
    if table is None:
        return []
    return list(early_warning.read_recent(table, day) or [])


def records_failsoft(table: Any = None) -> list[dict[str, Any]]:
    """Every disruption record from `table` (default: the generator's own), [] on a failed read (no mode claimed)."""
    from training import disruption  # noqa: PLC0415

    return disruption.load_records_failsoft(table)


def current(
    table: Any, day: str, *, records: Optional[list[dict[str, Any]]] = None, response: Optional[dict[str, Any]] = None
) -> Optional[dict[str, Any]]:
    """``mode`` over the live records, the flag rows and the response owner (owner channel). None on any trouble."""
    try:
        if response is None:
            from coach import response_protocol  # noqa: PLC0415

            response = response_protocol.current()
        recs = records if records is not None else (records_failsoft(table) if table is not None else [])
        return mode(recs, day, flag_rows=read_flag_rows(table, day), response=response)
    except Exception as e:  # noqa: BLE001 — a coach context is never load-bearing on this read
        logger.warning("[life_disruption] mode unavailable: %s", type(e).__name__)
        return None
