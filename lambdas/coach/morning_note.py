"""coach/morning_note.py — the morning note: four words before the number (#4189).

WHY THIS EXISTS
  Two coaches asked, on consecutive days (09-24 sleep coach, 09-25 mind coach), for a
  four-word note before the owner opens Whoop — "how do I feel before the number tells
  me?" — and nothing on the platform could receive it. This module is the ONE
  derivation every consumer of that note reads through: the site-api GET
  (`web.site_api_social_note.handle_morning_note_read`), the coach packet
  (`mcp.tools_coach_packet`) and the coach input boundary
  (`coach.coach_input_facts.coach_inputs`). The write door
  (`web.site_api_social_note._handle_morning_note`) stores the row this module reads;
  the pair is enrolled in `tests/pair_contract_registry.py`.

THE RECORD
  pk `USER#matthew#SOURCE#morning_note`, sk `MORNING_NOTE#<PT date>` —
  `{date, sleep_word, body_word, mood_word, felt_recovered: bool, written_at (UTC
  instant), tier, source}`. One note per Pacific day: the write is conditional
  (`attribute_not_exists(sk)`), and a second write the same day is REFUSED unless the
  owner says `replace: true` explicitly (#4307's replace-by-key rule).

ABSENCE SEMANTICS AT BIRTH (ADR-104 / ADR-154)
  No row = "no note that morning". Never a default, never an empty word, never a
  carried-forward yesterday. A failed read is `read_failed`, never `absent`.

PRIVACY (owner ruling 2026-09-26 ~23:15 PT, BUILD_WEEK_BRIEF §5 item 3)
  The ruling was asked on the brief's two-step scale: "Tier 1 — the words and day are
  public; Tier 2 — presence only". The owner ruled Tier 1. The stored `tier` field
  carries THAT scale (`NOTE_TIER_PUBLIC == 1`), and `public_view` honours it: a row at
  any other tier serves presence only. On `docs/DATA_GOVERNANCE.md`'s scale this is
  Tier 0 (public) — recorded there with the dated ruling; the two scales are named so
  neither is mistaken for the other.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from common.pacific_time import day_in_words, pacific_clock_label, parse_day_key, shift_day_key

MORNING_NOTE_PK = "USER#matthew#SOURCE#morning_note"
MORNING_NOTE_SK_PREFIX = "MORNING_NOTE#"
#: the brief's two-step ruling scale (1 = words + day public; 2 = presence only) — NOT
#: DATA_GOVERNANCE's 0..3 scale (see the module docstring).
NOTE_TIER_PUBLIC = 1
NOTE_TIER_PRESENCE_ONLY = 2
WORD_FIELDS = ("sleep_word", "body_word", "mood_word")
WORD_MAX_CHARS = 24
#: letters, single spaces and hyphens only — no digits, no punctuation, no URL can pass.
WORD_RE = re.compile(r"^[A-Za-z]+(?:[ -][A-Za-z]+)*$")
#: how far back "the latest note" looks by default (the site's "in his words this week"
#: needs 7; the read is one bounded query either way).
DEFAULT_LOOKBACK_DAYS = 14
MAX_LOOKBACK_DAYS = 31
#: the coach reads today's note, or yesterday's if he wrote none this morning yet — never older.
COACH_LOOKBACK_DAYS = 2
SOURCE_LABEL = "site_api_morning_note"

COACH_NOTE_INSTRUCTION = (
    "The owner's OWN four words, typed before he opened any number that morning. Quote them verbatim or not at "
    "all — never paraphrase, never infer a word he did not write, never grade them. Name the day in words "
    "(`day`), never the ISO date. `felt_recovered` is his call, not the recovery score's; when the two disagree, "
    "that disagreement is the observation. If `state` is absent there was no note — say nothing about it."
)


def sk_for(day: str) -> str:
    return f"{MORNING_NOTE_SK_PREFIX}{day}"


def validate_note_body(body: Any) -> tuple[Optional[dict], Optional[str]]:
    """(the validated fields, None) or (None, the 400 reason). Every field is checked RAW —
    type and shape — never coerced: `999` is not a word, `"yes"` is not a bool."""
    if not isinstance(body, dict):
        return None, "Body must be a JSON object"
    out: dict[str, Any] = {}
    for field in WORD_FIELDS:
        raw = body.get(field)
        if not isinstance(raw, str):
            return None, f"{field} must be a string"
        word = " ".join(raw.split())
        if not word or len(word) > WORD_MAX_CHARS:
            return None, f"{field} must be 1-{WORD_MAX_CHARS} characters"
        if not WORD_RE.match(word):
            return None, f"{field} must be letters, spaces or hyphens only"
        out[field] = word
    felt = body.get("felt_recovered")
    if not isinstance(felt, bool):
        return None, "felt_recovered must be true or false"
    out["felt_recovered"] = felt
    return out, None


def read_notes(table, today: str, days: int = DEFAULT_LOOKBACK_DAYS) -> Optional[list]:
    """The notes in the `days`-day window ending `today` (Pacific), NEWEST FIRST.

    `[]` = read fine, no note (absence). `None` = the read failed (unknown) — a caller
    must never render None as "no note". Bounded: `days` is clamped to MAX_LOOKBACK_DAYS.
    """
    if table is None or parse_day_key(today) is None:
        return None
    days = max(1, min(int(days), MAX_LOOKBACK_DAYS))
    start = shift_day_key(today, -(days - 1))
    try:
        from boto3.dynamodb.conditions import Key

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(MORNING_NOTE_PK) & Key("sk").between(sk_for(start), sk_for(today) + "~"),
            ScanIndexForward=False,
            Limit=days,
        )
        items = [i for i in (resp.get("Items") or []) if isinstance(i, dict) and str(i.get("sk", "")).startswith(MORNING_NOTE_SK_PREFIX)]
    except Exception as e:  # noqa: BLE001 — reported as read_failed by every caller, never as absence
        print(f"[MORNING-NOTE] read failed ({type(e).__name__}): {e}")
        return None
    return sorted(items, key=lambda i: str(i.get("sk")), reverse=True)


def _day_of(row: dict) -> Optional[str]:
    """The note's `date` field — never inferred from the sk: a row without it is a drift, not a note."""
    day = row.get("date")
    return day if isinstance(day, str) and parse_day_key(day) is not None else None


def public_view(row: dict) -> dict:
    """The served shape of one stored note, per its stored tier.

    Tier 1 (the ruling): `{state: "served", date, sleep_word, body_word, mood_word,
    felt_recovered, written_at}`. Any other tier: `{state: "present", date, written_at}`
    — presence only, the words withheld. A row missing a word is NOT served as a note
    with a blank in it: it raises, so a producer drift is a loud consumer failure.
    """
    day = _day_of(row)
    if day is None:
        raise ValueError("a morning note row carries no day")
    written_at = row.get("written_at")
    if not isinstance(written_at, str) or not written_at:
        raise ValueError(f"morning note {day} carries no written_at instant")
    if row.get("tier") != NOTE_TIER_PUBLIC:
        return {"state": "present", "date": day, "written_at": written_at, "tier": NOTE_TIER_PRESENCE_ONLY}
    out: dict[str, Any] = {"state": "served", "date": day, "written_at": written_at, "tier": NOTE_TIER_PUBLIC}
    for field in WORD_FIELDS:
        word = row.get(field)
        if not isinstance(word, str) or not word:
            raise ValueError(f"morning note {day} has no {field}")
        out[field] = word
    felt = row.get("felt_recovered")
    if not isinstance(felt, bool):
        raise ValueError(f"morning note {day}: felt_recovered is {type(felt).__name__}, not a bool")
    out["felt_recovered"] = felt
    return out


def coach_fact(row: Optional[dict], *, read_ok: bool = True) -> dict:
    """The note as a SERVED FACT for a coach input (`coach_input_facts`, the #4227 pattern)
    and for the coach packet: the words, the day in words, the write instant in PT, and
    the instruction. `state` is measured / absent / read_failed — a failed read is never
    an empty morning."""
    if not read_ok:
        return {"state": "read_failed", "note": "the morning-note read failed — unknown, never 'no note'"}
    if row is None:
        return {"state": "absent", "note": f"no morning note in the last {COACH_LOOKBACK_DAYS} days — never infer one"}
    view = public_view(row)
    written_pt = pacific_clock_label(view["written_at"], with_day=True)
    fact = {
        "state": "measured",
        "date": view["date"],
        "data_through": view["date"],
        "day": day_in_words(view["date"]),
        "written_at_pt": written_pt or view["written_at"],
        "tier": view["tier"],
        "note": COACH_NOTE_INSTRUCTION,
    }
    if view["state"] == "served":
        for field in WORD_FIELDS:
            fact[field] = view[field]
        fact["felt_recovered"] = view["felt_recovered"]
    else:
        fact["words"] = "withheld (presence-only tier)"
    return fact
