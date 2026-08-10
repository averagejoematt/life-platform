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

INSIDE REFERENCES (#2487). The same daily summarizer call now ALSO returns the
day's inside references — the recurring bits the pair actually built — kept in a
capped ``RELATIONSHIP#bits`` row and rendered back into the memory block. Four
deliberate choices:

* **One extraction path, not two.** The summarizer prompt already asks for "open
  loops, commitments"; asking the same Haiku call for a short ``BITS:`` tail is
  one more instruction on a call that has already read the transcript, versus a
  second model call over the same text.
* **Verbatim-or-nothing (ADR-104).** A candidate bit is stored only when its
  normalized text is literally present in the day's transcript
  (``grounded_bits``). The model may notice a bit; it may not invent one.
  Inference is not memory.
* **Capped, with a written eviction rule.** ``MAX_BITS`` is a hard ceiling on
  the row, enforced on every write by ``merge_bits``: the strongest bits are
  kept — most sightings first, then most recently used, then alphabetical as a
  final deterministic tiebreak — and everything past the ceiling is dropped.
  There is no unbounded growth path.
* **Read-folded, like #2489.** The bits join the prompt through
  ``read_recent_summaries``, the call ``_memory_block`` already makes, so the
  feature costs the size-guarded ``telegram_worker_lambda.py`` zero lines.

Reset semantics: ``COACH#*`` + ``RELATIONSHIP#*`` is CROSS_PHASE
(``lambdas/experiment/phase_taxonomy.py``, the ADR-153 rule) and a bits row is
deliberately inside that family. An inside reference is a fact about the
relationship, not about the experiment cycle it happened to be born in — wiping
it at a reset would make the coach forget a shared joke because a diet changed.
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

# Inside references (#2487, Coach Humanity Roadmap idea 16).
BITS_SK = "RELATIONSHIP#bits"
# The hard ceiling on the row. Ten is the issue's own bound and it is a real
# ceiling, not a guideline: merge_bits enforces it on every write, so the
# partition cannot grow past it no matter how many days write to it.
MAX_BITS = 10
# Per-day intake ceiling — a single chatty day cannot flush the whole ledger and
# replace the pair's history with one afternoon's phrasing.
MAX_NEW_BITS_PER_DAY = 3
_MAX_BIT_CHARS = 80
_BITS_MARKER = "BITS:"

_SYSTEM = (
    "You are the coach, jotting a private note to self after a day of texting "
    "with Matthew — 2-4 sentences you will rely on in later conversations. "
    "First person, the way a person actually remembers ('he asked what to eat', "
    "'I still need his food logs', 'follow up on the 5am gym plan'). Keep what "
    "a friend would remember: his state, open loops, commitments either of you "
    "made. Restate only what is actually in the transcript — never invent "
    "numbers or facts not present, and never editorialize about who was right. "
    "No preamble.\n\n"
    "After the note, on its own final line, write 'BITS:' followed by any inside "
    "references the two of you actually used today — a nickname, a running joke, "
    "a shorthand phrase — one per line, each prefixed with '- ', copied "
    "WORD-FOR-WORD from the transcript. Most days have none: write 'BITS: none'. "
    "Never paraphrase and never invent one; a missed bit costs nothing, an "
    "invented one is a lie about a shared history."
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
    # #2487: the inside-references ledger folds in HERE for the same reason the
    # time-gap line does — this call is already the one `_memory_block` makes, so
    # the feature reaches the prompt without touching the size-guarded worker.
    parts = [p for p in (gap_line, summary_text, bits_block(read_bits(table, pk))) if p]
    return "\n\n".join(parts)


def _normalize(text) -> str:
    return " ".join(str(text or "").lower().split())


def split_note_and_bits(raw: str) -> tuple:
    """Split the summarizer's reply into (note, candidate bits).

    The bits tail is optional in every direction: no marker, an empty marker, or
    a literal 'none' all yield ``[]`` and leave the note untouched. Parsing never
    raises — a malformed tail is simply a day with no bits.
    """
    text = str(raw or "")
    lowered = text.lower()
    idx = lowered.rfind(_BITS_MARKER.lower())
    if idx < 0:
        return text.strip(), []
    note = text[:idx].strip()
    tail = text[idx + len(_BITS_MARKER) :]
    candidates = []
    for line in tail.splitlines():
        line = line.strip().lstrip("-•*").strip().strip("\"'").strip()
        if not line or _normalize(line) in ("none", "no bits", "n/a"):
            continue
        candidates.append(line[:_MAX_BIT_CHARS])
    return note, candidates


def grounded_bits(candidates, transcript: str) -> list:
    """The ADR-104 gate: a bit survives only if it is LITERALLY in the day's
    transcript. The model is allowed to notice a running joke; it is not allowed
    to infer, paraphrase, or invent one — an inside reference the pair never
    actually said is a fabricated shared history, the most corrosive kind.

    Deduplicated on normalized text, capped at ``MAX_NEW_BITS_PER_DAY``.
    """
    hay = _normalize(transcript)
    kept: list = []
    seen = set()
    for c in candidates or []:
        norm = _normalize(c)
        if not norm or norm in seen or norm not in hay:
            continue
        seen.add(norm)
        kept.append(str(c).strip())
        if len(kept) >= MAX_NEW_BITS_PER_DAY:
            break
    return kept


def merge_bits(existing, new_bits, date: str) -> list:
    """Fold today's grounded bits into the stored ledger and enforce the cap.

    THE EVICTION RULE, deterministic and total: bits are ordered strongest-first
    by (1) sightings descending, (2) ``last_seen`` descending, (3) text ascending
    as the final tiebreak, and everything past ``MAX_BITS`` is dropped. So the
    bit that goes is always the one seen fewest times; ties broken by the one
    least recently used; ties broken alphabetically so two runs over the same
    input can never disagree.

    Re-sighting an existing bit (matched on normalized text) bumps its count and
    ``last_seen`` rather than adding a row — that is what makes a bit "recurring"
    instead of merely recent. Re-running the SAME date is idempotent: a bit
    already stamped with ``date`` is not counted twice.
    """
    merged = []
    index = {}
    for b in existing or []:
        text = str((b or {}).get("text") or "").strip()
        if not text:
            continue
        norm = _normalize(text)
        if norm in index:
            continue
        row: dict = {
            "text": text,
            "first_seen": str(b.get("first_seen") or date),
            "last_seen": str(b.get("last_seen") or date),
            "count": int(b.get("count") or 1),
        }
        index[norm] = row
        merged.append(row)
    for text in new_bits or []:
        text = str(text or "").strip()[:_MAX_BIT_CHARS]
        norm = _normalize(text)
        if not norm:
            continue
        row = index.get(norm)
        if row is None:
            row = {"text": text, "first_seen": date, "last_seen": date, "count": 1}
            index[norm] = row
            merged.append(row)
        elif row["last_seen"] != date:
            row["count"] = int(row["count"]) + 1
            row["last_seen"] = max(str(row["last_seen"]), date)
    # Stable sorts compose: text asc, then last_seen desc, then count desc.
    merged.sort(key=lambda b: b["text"])
    merged.sort(key=lambda b: b["last_seen"], reverse=True)
    merged.sort(key=lambda b: b["count"], reverse=True)
    return merged[:MAX_BITS]


def read_bits(table, pk: str) -> list:
    """The stored bits, newest-strongest first. Fail-soft to []."""
    try:
        item = table.get_item(Key={"pk": pk, "sk": BITS_SK}).get("Item") or {}
    except Exception as e:
        logger.warning("[chat_summary] bits read failed for %s: %s", pk, e)
        return []
    bits = item.get("bits")
    return list(bits) if isinstance(bits, list) else []


def bits_block(bits) -> str:
    """The prompt block. "" for an empty ledger — a coach with no shared bits
    yet must be told nothing rather than told it has none."""
    lines = []
    for b in bits or []:
        text = str((b or {}).get("text") or "").strip()
        if not text:
            continue
        count = int((b or {}).get("count") or 1)
        since = str((b or {}).get("first_seen") or "")
        seen = f", {count}x" if count > 1 else ""
        lines.append(f'- "{text}" (since {since}{seen})' if since else f'- "{text}"')
    if not lines:
        return ""
    return (
        "INSIDE REFERENCES (things the two of you actually said to each other — "
        "reuse one only when it lands naturally, never explain it, never force it):\n" + "\n".join(lines)
    )


def _store_bits(table, pk: str, new_bits, date: str, coach_name: str = "", cycle=None) -> Optional[list]:
    """Merge + write the capped row. Returns the stored list, or None when there
    was nothing to change. Never raises — bits are a nicety, chat is the job."""
    if not new_bits:
        return None
    try:
        merged = merge_bits(read_bits(table, pk), new_bits, date)
        item = {
            "pk": pk,
            "sk": BITS_SK,
            "type": "relationship_bits",
            "bits": merged,
            "coach_name": coach_name,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if cycle is not None:
            item["cycle"] = cycle
        table.put_item(Item=item)
        logger.info("[chat_summary] stored %d inside references for %s", len(merged), pk)
        return merged
    except Exception as e:
        logger.warning("[chat_summary] bits write failed for %s (chat unaffected): %s", pk, e)
        return None


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
                text = (block.get("text") or "").strip()
                break
        # #2487: the same reply carries the day's inside references in a BITS:
        # tail. Split it off BEFORE the note is stored so the tail never leaks
        # into the prose the coach reads back as "what I remember".
        text, bit_candidates = split_note_and_bits(text)
        text = text[:_MAX_SUMMARY_CHARS]
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
        # Only the worker that WON the conditional summary put gets here, so the
        # un-conditioned bits write is single-writer per day by construction.
        _store_bits(table, pk, grounded_bits(bit_candidates, transcript), target, coach_name=coach_name, cycle=cycle)
        return target
    except Exception as e:
        if e.__class__.__name__ == "ConditionalCheckFailedException":
            return None
        logger.warning("[chat_summary] ensure failed for %s (chat unaffected): %s", pk, e)
        return None
