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


def read_recent_summaries(table, pk: str, limit: int = MAX_SUMMARY_ROWS_IN_PROMPT) -> str:
    """The 'recent conversations' paragraph — newest-first summary rows, oldest
    rendered first so the narrative reads forward. "" when there are none."""
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
        return ""
    lines = []
    for r in rows:
        date = str(r.get("sk", ""))[len(SUMMARY_SK_PREFIX) :]
        text = str(r.get("text") or "").strip()
        if text:
            lines.append(f"[{date}] {text}")
    if not lines:
        return ""
    return "RECENT CONVERSATIONS (your own compressed notes from earlier days):\n" + "\n".join(f"- {ln}" for ln in lines)


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
