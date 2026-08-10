"""coach_chat_summary.py — the chat thread's long memory (coaching-team v2, Wave 2.6).

``MAX_THREAD_TURNS=12`` keeps the turn prompt bounded, which also means anything
said more than a dozen turns ago simply falls out of the coach's world. This
module closes that gap with one row per chat day: ``CHAT#summary#{date}`` — the
day's exchanges compressed to a short paragraph, read back into later prompts as
a single "recent conversations" block.

Two deliberate shape choices:

* **Lazily written, not scheduled.** The first turn of a LATER day writes the
  summary for the last un-summarized chat day, after its own reply has already
  gone out (zero perceived latency, no new EventBridge rule, nothing for the
  reset pipeline to learn about — the row keys inside the coach's own partition,
  which the worker's LeadingKeys grant already covers).
* **The sk lives INSIDE the CHAT# prefix on purpose** — the plan's reset-proofing
  names CHAT#/CHAT#summary as one cross-phase family. The thread reader filters
  by ``role`` (matthew/coach), so a summary row can never masquerade as a turn;
  ``tests/test_coach_texting_behavior.py`` pins that.

The summarizer model is Haiku (structured task, ADR-049 tiering) through
``bedrock_client.invoke`` (ADR-062). Every path fails soft: a chat with no
summary is exactly yesterday's behaviour, never an error.

TIME-GAP AWARENESS (#2489). ``read_recent_summaries`` also carries a "been a
minute" memory line when the real chat history shows a quiet stretch (>=
``QUIET_GAP_DAYS``). It is folded into THIS module's output rather than added as
a new call site because the actual assembly point — ``_memory_block`` in
``telegram_worker_lambda.py`` — is a concurrently-edited, size-guarded file this
change must not touch (three sibling coach-humanity PRs were landing at the same
time); ``read_recent_summaries(table, pk)`` is already the exact call
``_memory_block`` makes, so extending its return value wires the feature in with
zero touches to that file. The date comes from the real ``CHAT#`` turn rows, not
the ``CHAT#summary#`` rows — a summary is written lazily on the FOLLOWING day's
first turn, so the newest summary date can silently lag the true last-chat date
by exactly the gap this feature exists to name.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SUMMARY_SK_PREFIX = "CHAT#summary#"
HAIKU_MODEL = os.environ.get("AI_MODEL_HAIKU", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_SUMMARY_ROWS_IN_PROMPT = 3
_MAX_TRANSCRIPT_CHARS = 6000
_MAX_SUMMARY_CHARS = 600

# Time-gap awareness (#2489, Coach Humanity Roadmap idea 19). "Quiet week" from the
# issue title, made a named constant rather than a magic number: a gap of AT LEAST
# this many days is a real absence worth a natural "been a minute" acknowledgement;
# anything shorter is just... texting, and must never draw comment (an active,
# same-day or few-day thread getting gap commentary would read as the coach not
# paying attention, the opposite of the intended effect).
QUIET_GAP_DAYS = 7

_SYSTEM = (
    "You are the coach, jotting a private note to self after a day of texting "
    "with Matthew — 2-4 sentences you will rely on in later conversations. "
    "First person, the way a person actually remembers ('he asked what to eat', "
    "'I still need his food logs', 'follow up on the 5am gym plan'). Keep what "
    "a friend would remember: his state, open loops, commitments either of you "
    "made. Restate only what is actually in the transcript — never invent "
    "numbers or facts not present, and never editorialize about who was right. "
    "No preamble."
)


def summary_sk(date_str: str) -> str:
    return f"{SUMMARY_SK_PREFIX}{date_str}"


def is_summary_row(item: dict) -> bool:
    return str((item or {}).get("sk", "")).startswith(SUMMARY_SK_PREFIX)


def read_recent_summaries(table, pk: str, limit: int = MAX_SUMMARY_ROWS_IN_PROMPT, today: Optional[str] = None) -> str:
    """The 'recent conversations' paragraph — newest-first summary rows, oldest
    rendered first so the narrative reads forward — prefixed with the time-gap
    line (#2489, ``time_gap_line``) when the real chat history shows a quiet
    stretch. "" when there is neither a summary nor a gap to report.

    ``today`` is accepted (not just read from the wall clock) so a caller — and a
    test — can pin the date deterministically; it defaults to the real UTC date.
    """
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": pk, ":pfx": SUMMARY_SK_PREFIX},
            ScanIndexForward=False,
            Limit=limit,
        )
        rows = list(reversed(resp.get("Items") or []))
    except Exception as e:
        logger.warning("[chat_summary] read failed for %s: %s", pk, e)
        rows = []
    lines = []
    for r in rows:
        date = str(r.get("sk", ""))[len(SUMMARY_SK_PREFIX) :]
        text = str(r.get("text") or "").strip()
        if text:
            lines.append(f"[{date}] {text}")
    summary_text = (
        "RECENT CONVERSATIONS (your own compressed notes from earlier days):\n" + "\n".join(f"- {ln}" for ln in lines) if lines else ""
    )
    gap_line = time_gap_line(table, pk, today=today)
    if gap_line and summary_text:
        return f"{gap_line}\n\n{summary_text}"
    return gap_line or summary_text


def _latest_chat_date(table, pk: str, scan_limit: int = 60) -> Optional[str]:
    """The date of the most recent REAL chat turn (role matthew/coach), skipping
    ``CHAT#summary#`` rows — see the module docstring for why a summary row is
    the wrong signal for this. ``None`` when no real turn exists in the scanned
    window, including a genuinely empty partition (a coach Matthew has never
    texted) — never invented, never a crash.
    """
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": pk, ":pfx": "CHAT#"},
            ScanIndexForward=False,
            Limit=scan_limit,
        )
    except Exception as e:
        logger.warning("[chat_summary] latest-turn read failed for %s: %s", pk, e)
        return None
    for it in resp.get("Items") or []:
        if is_summary_row(it) or it.get("role") not in ("matthew", "coach"):
            continue
        sk = str(it.get("sk", ""))
        return sk[len("CHAT#") :].split("#")[0]
    return None


def time_gap_line(table, pk: str, today: Optional[str] = None) -> str:
    """The "been a minute" memory line (#2489) — a factual last-chat date/gap
    PLUS the instruction for how to use it, carried together because this
    module has no seam into the CONVERSATION RULES prompt block in
    ``coach_chat.py`` (that block, and its `#2481` register-matching/
    question-budget content, is under active concurrent edit + heavy existing
    test coverage — see the module docstring for the full reasoning). "" when:

    * the partition has no real prior turn at all (nothing to be quiet ABOUT —
      a brand-new thread must never open with "been a minute"), or
    * the gap is shorter than ``QUIET_GAP_DAYS`` (an active thread must never
      get gap commentary — same-day and few-day back-and-forth is normal).
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_date = _latest_chat_date(table, pk)
    if not last_date:
        return ""
    try:
        gap_days = (datetime.strptime(today, "%Y-%m-%d").date() - datetime.strptime(last_date, "%Y-%m-%d").date()).days
    except ValueError:
        return ""
    if gap_days < QUIET_GAP_DAYS:
        return ""
    return (
        f"TIME GAP: it has been {gap_days} days since your last conversation with Matthew (you last texted on "
        f"{last_date}). That is a real quiet stretch, not an ongoing thread — acknowledge it naturally and briefly, "
        "the way a person notices time passed with someone they know ('hey, been a minute'), then move on to what "
        "he actually said. Never mention this, or any gap, when the thread has been active."
    )


def _chat_days(table, pk: str, today: str, scan_limit: int = 120) -> list:
    """Distinct chat dates present in the newest turns, excluding today."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": pk, ":pfx": "CHAT#"},
        ScanIndexForward=False,
        Limit=scan_limit,
    )
    days = set()
    for it in resp.get("Items") or []:
        if is_summary_row(it) or it.get("role") not in ("matthew", "coach"):
            continue
        sk = str(it.get("sk", ""))
        date = sk[len("CHAT#") :].split("#")[0]
        if date and date < today:
            days.add(date)
    return sorted(days)


def _day_transcript(table, pk: str, date: str) -> str:
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": pk, ":pfx": f"CHAT#{date}#"},
        ScanIndexForward=True,
    )
    lines = []
    for it in resp.get("Items") or []:
        role = it.get("role")
        text = str(it.get("text") or "").strip()
        if role in ("matthew", "coach") and text:
            speaker = "Matthew" if role == "matthew" else "Coach"
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)[:_MAX_TRANSCRIPT_CHARS]


def ensure_daily_summary(
    table,
    pk: str,
    coach_name: str,
    caller: Callable[[dict], dict],
    today: Optional[str] = None,
    cycle=None,
) -> Optional[str]:
    """Write the summary row for the most recent un-summarized past chat day.

    Returns the date summarized, or None when there was nothing to do. Runs
    AFTER a reply has been sent — its failure modes are all "no summary yet",
    never a broken chat. The conditional put makes concurrent workers converge.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        days = _chat_days(table, pk, today)
        if not days:
            return None
        target = days[-1]
        if table.get_item(Key={"pk": pk, "sk": summary_sk(target)}).get("Item"):
            return None
        transcript = _day_transcript(table, pk, target)
        if not transcript.strip():
            return None
        response = caller(
            {
                "model": HAIKU_MODEL,
                "max_tokens": 300,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": f"Transcript of {target}:\n\n{transcript}"}],
            }
        )
        text = ""
        for block in (response or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()[:_MAX_SUMMARY_CHARS]
                break
        if not text:
            return None
        item = {
            "pk": pk,
            "sk": summary_sk(target),
            "type": "chat_summary",
            "text": text,
            "coach_name": coach_name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if cycle is not None:
            item["cycle"] = cycle
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
        logger.info("[chat_summary] wrote %s for %s", summary_sk(target), pk)
        return target
    except Exception as e:
        if e.__class__.__name__ == "ConditionalCheckFailedException":
            return None
        logger.warning("[chat_summary] ensure failed for %s (chat unaffected): %s", pk, e)
        return None
