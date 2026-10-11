"""tools_owner_words.py — INLET A of the owner-words store: his Claude chat (#4584, epic #4580).

``log_owner_note`` stores words Matthew gives in chat, EXACTLY as he gave them, in ``USER#matthew#SOURCE#owner_words``
(``lambdas/content/owner_words.py`` owns the record, the filter and the serve). A clean entry is public on the site
word for word (owner decision 2026-10-04: a clean note is public); a held one is stored and never served.

The tool never writes in his voice: it stores the ``text`` argument byte for byte, and its description tells the
calling model that the text must be his own words, not a summary or a paraphrase. It answers with the verdict in
plain words and never names what the filter matched.
"""

from common.pacific_time import pacific_today, parse_day_key
from content import owner_words  # bundled shared module (#781): lambdas/ is staged at the zip root
from experiment.phase_taxonomy import experiment_stamp_for

from mcp.config import logger, table as _table_ref

LOG_OWNER_NOTE_DESCRIPTION = (
    "#4584: store Matthew's OWN words for the site's 'in his own words' block, exactly as he said them. Call it only "
    "when he asks for something he said to go on the site or 'on the record' (e.g. 'put this on the site: …', "
    "'log this as my note: …', 'my answer to this week's question is …'). text = his words VERBATIM — copy them "
    "character for character: never summarise, paraphrase, correct, tidy, translate or add to them, and never write "
    "words for him. If he has not given the exact words, ask him for them instead of calling. prompt = the question "
    "his words answer, if there is one. off_record = true when he says it is off the record (stored, never "
    "published). date = the day the words are about, YYYY-MM-DD, default today (Pacific). A clean note is PUBLIC on "
    "averagejoematt.com word for word; anything the privacy filter matches is held (stored, never published). The "
    "result's `verdict` says which, in plain words — tell him that sentence as it is."
)

LOG_OWNER_NOTE_INPUT = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "His words, exactly as he gave them. Stored and published byte for byte."},
        "prompt": {"type": "string", "description": "Optional: the question his words answer (published beside them)."},
        "off_record": {"type": "boolean", "description": "Optional: true = stored, never published."},
        "date": {"type": "string", "description": "Optional: the day the words are about, YYYY-MM-DD. Default: today (Pacific)."},
    },
    "required": ["text"],
}


def tool_log_owner_note(args):
    """Store one entry from chat; return its verdict in plain words."""
    args = args or {}
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"error": "text is required: his words, exactly as he gave them. Nothing was stored."}
    prompt = args.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        return {"error": "prompt must be text. Nothing was stored."}
    off_record = args.get("off_record", False)
    if not isinstance(off_record, bool):
        return {"error": "off_record must be true or false. Nothing was stored."}
    today = pacific_today()
    day = args.get("date") or today
    if not isinstance(day, str) or parse_day_key(day) is None or len(day) != 10:
        return {"error": f"date must be a day as YYYY-MM-DD (got {day!r}). Nothing was stored."}
    if day > today:
        return {"error": f"date {day} is after today ({today}, Pacific). Nothing was stored."}

    entry = owner_words.make_entry(
        text, channel=owner_words.CHANNEL_CHAT, day=day, received_at=owner_words.utc_now(), prompt=prompt, off_record=off_record
    )
    try:
        stored, created = owner_words.record(_table_ref, entry, stamp=experiment_stamp_for)
    except Exception as e:  # noqa: BLE001 — a lost note must be loud
        logger.warning(f"[#4584] owner note write failed: {type(e).__name__}")
        return {"error": f"the note could not be stored ({type(e).__name__}). Nothing was published; try again."}
    out = {
        "stored": True,
        "duplicate": not created,
        "verdict": owner_words.verdict_in_words(stored),
        "published": stored.get("verdict") == owner_words.VERDICT_CLEAN,
        "date": stored.get("date"),
        "channel": stored.get("channel"),
        "prompt": stored.get("prompt"),
        "entry_id": stored.get("sk"),
    }
    if not created:
        out["note"] = "This exact note was already stored for that day, so nothing was written a second time."
    return out
