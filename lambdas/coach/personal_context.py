"""coach/personal_context.py — the READERS behind the one personal-context assembly (#6291, epic #6284).

ONE assembly, two interfaces. `coach.coach_context_pilot.build_turn_context` is the single builder of what a coach
knows about Matthew; the Telegram worker (`for_turn`) and the Claude session packet (`packet_context`) both call it,
so the two interfaces cannot drift into two different understandings of him. This module holds the reads that
assembly needs and that used to live in one channel only:

  * `memory_core` / `chat_rows` — the coach's own memory partition (relationship state, commitments, learnings, the
    compressed notes, the corrections block) and its stored chat turns. Moved here VERBATIM from the Telegram worker
    (`_memory_block` / `_chat_rows`, which now call these), so the session packet reads the same memory the phone
    thread does instead of a second copy.
  * `scan_section` — the stored body-composition scan, dated and labelled so old evidence reads as old (#6226 case 1).
  * `intake_section` — logged intake against the intake implied by the weight trend and estimated expenditure, with
    its window and caveats (#6226 case 2), computed by `health.grounded_intake_facts` (#6212), never re-derived here.
  * `latest_message_section` — his newest stored message, marked as the latest thing he asked, ahead of the coach's
    own notes (#6226 case 3; the November miss that named the newest NOTE instead).

Every reader is bounded (a `Limit` on every query) and fail-soft: a failed read returns "" / [] / None and logs its
error CLASS, so a context read can never cost him a reply. Nothing here writes, and nothing here reads a
model-inferred psychological field (#6286).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

try:  # the worker's own logger (#3283 / #5106): these lines reach the same CloudWatch stream as before the move
    from common.platform_logger import get_logger

    logger: logging.Logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

USER_PREFIX = "USER#matthew#SOURCE#"
DATE_PREFIX = "DATE#"

#: Seats the two #6226 facts reach. The lead sees everything; the scan is the Performance and nutrition seats' evidence,
#: the intake reconciliation the nutrition seat's. A seat outside the set gets no section (and costs no read).
LEAD_PERSONA = "eli_marsh"
SCAN_PERSONAS = frozenset({LEAD_PERSONA, "physical_coach", "training_coach", "nutrition_coach"})
INTAKE_PERSONAS = frozenset({LEAD_PERSONA, "nutrition_coach"})

SCAN_QUERY_LIMIT = 5
#: The intake window is `grounded_intake_facts.WINDOW_MAX_DAYS` (63) — plus the 7-day phase-start weight search when the
#: genesis is further back. One row per day per source, so 120 bounds every series read with room to spare.
SERIES_QUERY_LIMIT = 120
KJ_PER_KCAL = 4.184
EXPENDITURE_SOURCE = "Whoop daily energy estimate (kilojoule, keyed by UTC day, converted at 4.184 kJ per kcal)"

SCAN_HEADER = "3b. BODY-COMPOSITION SCAN ON FILE (a stored, dated measurement; old evidence reads as old):"
INTAKE_HEADER = (
    "3c. LOGGED INTAKE AGAINST THE INTAKE IMPLIED BY HIS WEIGHT CHANGE (a computed estimate with its window and caveats; "
    "implied intake is never measured intake):"
)
LATEST_HEADER = {
    "telegram": "4a. HIS MOST RECENT MESSAGE BEFORE THE ONE YOU ARE ANSWERING",
    "session": "4a. HIS MOST RECENT MESSAGE TO THIS COACH IN THE TELEGRAM CHAT",
}


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _clip(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _in_words(day: str) -> str:
    try:
        from common.pacific_time import day_in_words

        return f"{day_in_words(day)} ({day})"
    except Exception:  # noqa: BLE001 — a date label is never load-bearing
        return day


def _days_between(a: str, b: str) -> Optional[int]:
    from common.pacific_time import parse_day_key

    da, db = parse_day_key(a), parse_day_key(b)
    return None if da is None or db is None else (db - da).days


# ── the coach's own memory partition (moved from the Telegram worker, unchanged) ─────────────


def chat_rows(table, coach_id: str, limit: int = 40) -> list:
    """The coach's recent CHAT# turn rows, oldest-first, WHOLE items (the worker's `_chat_rows`, moved verbatim).

    Role filter, not just a text filter: CHAT#summary# rows live inside the CHAT# prefix by design and must never be
    read back as turns."""
    from coach import coach_chat

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": coach_chat.chat_pk(coach_id), ":pfx": coach_chat.CHAT_SK_PREFIX},
            ScanIndexForward=False,
            Limit=limit,
        )
        items = list(reversed(resp.get("Items") or []))
        return [i for i in items if i.get("role") in (coach_chat.ROLE_MATTHEW, coach_chat.ROLE_COACH)]
    except Exception as e:
        logger.warning("[telegram] thread read failed for %s: %s", coach_id, e)
        return []


def memory_core(table, coach_id: str) -> str:
    """What this coach knows about Matthew — relationship state + recent memory rows + notes + corrections (the
    worker's `_memory_block`, moved verbatim). Fail-soft per read."""
    from coach import coach_chat

    pk = coach_chat.chat_pk(coach_id)
    lines = []
    try:
        # #946/#1969: a restart tombstones singletons IN PLACE — an unguarded get_item
        # would feed the wiped cycle's relationship arc into a fresh-cycle chat.
        from experiment.phase_filter import singleton_visible

        rel = table.get_item(Key={"pk": pk, "sk": "RELATIONSHIP#state"}).get("Item") or {}
        if not singleton_visible(rel):
            rel = {}
        phase = rel.get("phase")
        if phase:
            lines.append(f"Your working relationship with Matthew is in the '{phase}' phase.")
    except Exception as e:
        logger.warning("[telegram] relationship read failed: %s", e)
    for prefix, label, cap in (("COMMITMENT#", "Commitments you hold him to", 3), ("LEARNING#", "Things you have learned about him", 3)):
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
                ExpressionAttributeValues={":pk": pk, ":pfx": prefix},
                ScanIndexForward=False,
                Limit=cap,
            )
            rows = [str(i.get("text") or i.get("commitment") or i.get("learning") or "").strip() for i in resp.get("Items") or []]
            rows = [r for r in rows if r]
            if rows:
                lines.append(f"{label}: " + " · ".join(rows))
        except Exception as e:
            logger.warning("[telegram] %s read failed: %s", prefix, e)
    block = ("WHAT YOU REMEMBER ABOUT MATTHEW:\n" + "\n".join(f"- {ln}" for ln in lines)) if lines else ""
    # The long memory: yesterday-and-earlier compressed to a paragraph, so what
    # he told this coach three days ago survives MAX_THREAD_TURNS.
    try:
        from coach.coach_chat_summary import read_recent_summaries

        block = "\n\n".join(b for b in (block, read_recent_summaries(table, pk)) if b)
    except Exception as e:
        logger.warning("[telegram] chat summaries unavailable: %s", e)
    # #6149: what he has already corrected this coach on (any owner-facing surface) — memory rides the
    # DYNAMIC tail of the system prompt, never the cached prefix; fail-soft to "" inside the helper.
    from coach.coach_corrections import chat_corrections_block

    return "\n\n".join(b for b in (block, chat_corrections_block(table, coach_id)) if b)


# ── 3b. the stored body-composition scan (#6226 case 1) ─────────────────────────────────────


def _day_rows(table, source: str, lo: str, hi: str, limit: int) -> list:
    """Day rows of one cross-phase source in [lo, hi], newest first. No phase filter on purpose: the body's timeseries
    and its scans do not reset with the experiment (#2089) — the window is what bounds recency, not the phase tag."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
        ExpressionAttributeValues={":pk": USER_PREFIX + source, ":lo": DATE_PREFIX + lo, ":hi": DATE_PREFIX + hi + "~"},
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for r in resp.get("Items") or []:
        sk = str(r.get("sk") or "")
        if r.get("tombstone") or r.get("deleted_at") or len(sk) != len(DATE_PREFIX) + 10:
            continue  # one row per day: a DATE#<day>#<suffix> sub-row is not the day row
        out.append(r)
    return out


def _flat_scan(row: dict) -> dict:
    """A stored DEXA row (live shape: `body_composition.*`, SCHEMA.md) as the flat scan `grounded_intake_facts` reads."""
    bc = row.get("body_composition") or {}
    return {
        "date": str(row.get("scan_date") or str(row.get("sk") or "")[len(DATE_PREFIX) :])[:10],
        "provider": row.get("provider"),
        "weight_lb": _num(bc.get("total_mass_lb")),
        "lean_mass_lb": _num(bc.get("lean_mass_lb")),
        "fat_mass_lb": _num(bc.get("fat_mass_lb")),
        "body_fat_pct": _num(bc.get("body_fat_pct")),
    }


def read_scans(table, day: str) -> list:
    return [_flat_scan(r) for r in _day_rows(table, "dexa", "0000-01-01", day, SCAN_QUERY_LIMIT)]


def _phase_start() -> Optional[str]:
    from common.constants import EXPERIMENT_START_DATE

    return str(EXPERIMENT_START_DATE) if EXPERIMENT_START_DATE else None


def _weights(table, day: str, phase_start: Optional[str]) -> dict:
    from common.pacific_time import shift_day_key
    from health import grounded_intake_facts as gif

    lo = shift_day_key(day, -(gif.WINDOW_MAX_DAYS - 1))
    if phase_start and phase_start < lo:
        lo = phase_start  # the scan label compares against the phase-start weight
    lo = max(lo, shift_day_key(day, -(SERIES_QUERY_LIMIT - 1)))
    rows = _day_rows(table, "withings", lo, day, SERIES_QUERY_LIMIT)
    return {str(r["sk"])[len(DATE_PREFIX) :]: _num(r.get("weight_lbs")) for r in rows if _num(r.get("weight_lbs")) is not None}


def scan_section(table, persona_id: str, day: str) -> str:
    """The newest stored scan with its date, its age and its label, or "" when this seat does not read scans. With no
    scan stored it says so — a coach then asserts neither a baseline nor its absence elsewhere."""
    if persona_id not in SCAN_PERSONAS:
        return ""
    try:
        from health import grounded_intake_facts as gif

        scans = read_scans(table, day)
        phase_start = _phase_start()
        fact = gif.scan_fact(
            as_of=day, scans=scans, weight_by_day=_weights(table, day, phase_start) if scans else {}, phase_start=phase_start
        )
        if not fact:
            return ""
        if not scans:
            return f"{SCAN_HEADER}\n- {fact['statement']}"
        newest = max(scans, key=lambda s: s["date"])
        figures = [
            f"{name} {newest[key]:g}{unit}"
            for key, name, unit in (
                ("weight_lb", "total mass", " lb"),
                ("lean_mass_lb", "lean mass", " lb"),
                ("fat_mass_lb", "fat mass", " lb"),
                ("body_fat_pct", "body fat", "%"),
            )
            if newest.get(key) is not None
        ]
        age = _days_between(newest["date"], day)
        when = f"dated {_in_words(newest['date'])}" + (f", {age} days before today" if age is not None else "")
        line = f"- Scan {when}: " + (", ".join(figures) + ". " if figures else "") + fact["statement"]
        rule = (
            "These figures describe his body ON THAT DATE only: name the date whenever you cite one, never present them as "
            "his current body composition, and never say no scan is on file."
        )
        return f"{SCAN_HEADER}\n{line}\n{rule}"
    except Exception as e:  # noqa: BLE001 — a scan read never costs a reply
        logger.warning("[personal_context] scan section unavailable: %s", type(e).__name__)
        return ""


# ── 3c. logged intake against implied intake (#6226 case 2) ─────────────────────────────────


def intake_fact(table, day: str) -> Optional[dict]:
    """`grounded_intake_facts.intake_fact` over the three stored series it needs, or None when they cannot support it.

    Intake is the food log (`macrofactor.total_calories_kcal`), weight the weigh-ins (`withings.weight_lbs`),
    expenditure Whoop's daily energy (`whoop.kilojoule`) — the one usable expenditure series (research session
    2026-11-22: the Apple series changes regime when the watch arrived). The complete-log line is the platform's one
    line (`grounded_intake_facts.default_complete_log_kcal`)."""
    from common.pacific_time import shift_day_key
    from health import grounded_intake_facts as gif

    lo = shift_day_key(day, -(gif.WINDOW_MAX_DAYS - 1))
    intake = {
        str(r["sk"])[len(DATE_PREFIX) :]: _num(r.get("total_calories_kcal"))
        for r in _day_rows(table, "macrofactor", lo, day, SERIES_QUERY_LIMIT)
        if _num(r.get("total_calories_kcal")) is not None
    }
    expenditure = {
        str(r["sk"])[len(DATE_PREFIX) :]: _num(r.get("kilojoule")) / KJ_PER_KCAL
        for r in _day_rows(table, "whoop", lo, day, SERIES_QUERY_LIMIT)
        if _num(r.get("kilojoule"))
    }
    return gif.intake_fact(
        as_of=day,
        intake_by_day=intake,
        weight_by_day=_weights(table, day, None),
        expenditure_by_day=expenditure,
        expenditure_source=EXPENDITURE_SOURCE,
        complete_log_kcal=gif.default_complete_log_kcal(),
        phase_start=_phase_start(),
    )


def render_intake(fact: dict) -> str:
    b = fact["basis"]
    lo, hi = b["implied_intake_kcal"]
    wlo, whi = b["implied_intake_widened_kcal"]
    window = (
        f"- Window: {_in_words(b['window_start'])} to {_in_words(b['window_end'])} ({b['window_days']} days; {b['weigh_ins']} "
        f"weigh-ins, weight trend {b['weight_slope_lb_per_week']:+g} lb a week). Implied intake about {lo:,}–{hi:,} kcal a day, "
        f"{wlo:,}–{whi:,} with the expenditure error band. Logged mean on complete-log days {b['logged_mean_complete_days_kcal']:,} "
        f"kcal ({b['complete_days']} complete, {b['partial_days']} partial, {b['missing_days']} missing days)."
    )
    limits = " ".join(fact.get("limits") or [])
    return f"{INTAKE_HEADER}\n- {fact['statement']}\n{window}\n- Caveats: {fact['uncertainty']} {limits}"


def intake_section(table, persona_id: str, day: str) -> str:
    if persona_id not in INTAKE_PERSONAS:
        return ""
    try:
        fact = intake_fact(table, day)
        if not fact:
            return f"{INTAKE_HEADER}\n- Not computable today: the stored food log, weigh-ins or expenditure do not cover enough days."
        return render_intake(fact)
    except Exception as e:  # noqa: BLE001 — never a guessed reconciliation
        logger.warning("[personal_context] intake section unavailable: %s", type(e).__name__)
        return ""


# ── 4a. his latest message, marked latest (#6226 case 3) ────────────────────────────────────


def latest_message_section(thread: list, notes: str, *, channel: str = "telegram", sent_day=None, note_days=None) -> str:
    """His newest stored message, quoted and dated, marked as the latest thing he asked or told this coach — and placed
    AHEAD of the coach's notes, because the November evaluation's coach named its newest dated NOTE as "the last thing
    you asked" when newer chat messages existed. `thread` is in send order (the assembly's `order_thread`)."""
    from coach import coach_chat

    mine = [t for t in thread or [] if t.get("role") == coach_chat.ROLE_MATTHEW and t.get("text")]
    if not mine:
        return ""
    newest = mine[-1]
    day = sent_day(newest) if sent_day else None
    label = _in_words(day) if day else "undated (no timestamp stored; the newest in stored order)"
    newest_note = max(note_days) if note_days else None
    if newest_note and day and newest_note > day:
        rel = (
            f" Your newest note is dated {_in_words(newest_note)}, later than this message: anything he said after it "
            "survives only in that note."
        )
    elif newest_note and day == newest_note:
        rel = f" Your newest note is dated the same day ({_in_words(newest_note)}); this message, not the note, is the latest."
    elif newest_note and day:
        rel = f" It is newer than your newest note, dated {_in_words(newest_note)}."
    else:
        rel = ""
    return (
        f'{LATEST_HEADER.get(channel, LATEST_HEADER["telegram"])}, sent {label}: "{_clip(newest.get("text"), 280)}" — the latest '
        f"thing he asked or told you. When he asks what he last asked or told you, it is this message, not a note.{rel}"
    )
