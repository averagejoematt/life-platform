"""
elena_state_updater.py — Elena Voss gets a mind (#537).

The platform's most-surfaced persona (Wednesday chronicle author, between-
chronicle emails, podcast host, homepage one-liner, reader Q&A byline) had no
memory system at all — continuity was "feed the prior installments into the
prompt". This lambda gives her the machinery the coaches already have
(coach_state_updater pattern): after each PUBLISHED installment, one Haiku
extraction updates a persistent PERSONA#elena partition.

DDB patterns (PK=PERSONA#elena):
  SK=THREAD#{date}#{slug}     narrative threads — status open/resolved, aged by week
  SK=CALLBACK#{date}#{slug}   promises made to readers — due by week N+3 (default),
                              status pending/paid; overdue ones become OBLIGATIONS
                              in the next chronicle prompt (the payoff is enforced)
  SK=MOTIF#state              running motifs (single record, merged per week)
  SK=STANCE#{date} + STANCE#latest
                              editorial stance WITH RECEIPTS — an evolution claim
                              is kept only when grounded in receipts from the
                              installment (the coach stance _sanitize discipline,
                              ADR-104 applied to the narrator herself)

Invoked async (Event) with {"date": "YYYY-MM-DD"} from the chronicle PUBLISH
paths only — chronicle-approve's approve handler and its stale-draft sweep —
never at draft time, so a rejected draft can't poison her memory. The
installment text is read back from the chronicle record in DynamoDB.

Budget: one Haiku call per published chronicle (weekly). Pauses with the other
narrative features at tier 1 (ADR-063) — a skip is fail-soft, state just ages.

v1.0.0 — 2026-07-04 (#537, epic #527)
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from phase_filter import singleton_visible  # #946: hide reset-tombstoned persona state

try:
    from platform_logger import get_logger

    logger = get_logger("elena-state-updater")
except ImportError:
    logger = logging.getLogger("elena-state-updater")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

PERSONA_PK = "PERSONA#elena"
CHRONICLE_PK = f"USER#{USER_ID}#SOURCE#chronicle"

# Callback due-window: a promise made in installment N is due by N + 3 weeks
# unless the extraction says otherwise (clamped — never immediate, never a year).
DEFAULT_CALLBACK_DUE_WEEKS = 3
MIN_CALLBACK_DUE_WEEKS = 1
MAX_CALLBACK_DUE_WEEKS = 6

# Bounded state (the #410 lesson — never pour an unbounded partition into a prompt)
MAX_OPEN_THREADS = 12
MAX_PENDING_CALLBACKS = 10
MAX_MOTIFS = 12
MAX_INSTALLMENT_CHARS = 14_000

# The stance must speak to editorial THINKING, never fabricate raw vitals —
# same discipline as the coach stance engine (coach_history_summarizer).
_RAW_VITAL_RE = re.compile(
    r"\b\d{2,3}\s?(?:bpm|ms|mg/?dl|lbs?|kg|kcal|cal)\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|\b\d{1,3}(?:\.\d+)?\s?%",
    re.IGNORECASE,
)
_CHANGE_RE = re.compile(
    r"\b(?:chang|shift|revis|reconsider|no longer|used to|previously|earlier I|"
    r"moved (?:on |from )|updated my|come around|changed my mind|where I once)",
    re.IGNORECASE,
)

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# DDB helpers
# ══════════════════════════════════════════════════════════════════════════════


def _get_item(pk, sk, consistent=False):
    """consistent=True for the installment read — the publish paths invoke this
    lambda milliseconds after flipping status to published, and an eventually-
    consistent read could still see the draft and skip the week."""
    try:
        item = table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=consistent).get("Item")
        # #946: get_item bypasses the phase filter — a restart-tombstoned singleton
        # (MOTIF#state, STANCE#latest, chronicle installment) is the OLD cycle's
        # narrative state and must not seed the new cycle's episodes.
        if not singleton_visible(item):
            return None
        return item
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _query_prefix(pk, sk_prefix, limit=100):
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            ScanIndexForward=False,
            Limit=limit,
        )
        # #946: PERSONA#elena THREAD#/CALLBACK# rows survive a reset with a
        # tombstone; without this filter EP1+ would "pay off" promises about a
        # storyline the new cycle's readers never saw.
        return [it for it in resp.get("Items", []) if singleton_visible(it)]
    except Exception as e:
        logger.warning("query(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _slugify(text, max_len=40):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:max_len] or "unnamed"


# ══════════════════════════════════════════════════════════════════════════════
# Haiku extraction (ADR-062: Bedrock via retry_utils.call_anthropic_raw)
# ══════════════════════════════════════════════════════════════════════════════

EXTRACTION_SYSTEM_PROMPT = (
    "You maintain the persistent memory of Elena Voss, the embedded journalist who "
    "writes 'The Measured Life' — a weekly chronicle of Matthew's real N=1 health "
    "experiment. After each published installment you update her notebook: narrative "
    "threads, promises made to readers (callbacks), running motifs, and her editorial "
    "stance toward the experiment's claims.\n\n"
    "## RULES\n"
    "- Ground EVERYTHING in the installment text provided. Never invent threads, "
    "promises, or stance changes the text doesn't support.\n"
    "- A CALLBACK is an explicit or strongly implied promise to the reader ('we'll "
    "know in two weeks', 'I'll be watching the bloodwork', 'more on that when the "
    "data lands'). Only real promises — not every forward reference.\n"
    "- A THREAD is an unresolved narrative tension carried across installments "
    "(a pattern being watched, a question raised, a conflict between coaches).\n"
    "- 'callbacks_paid' / 'threads_resolved' may ONLY reference slugs from the "
    "CURRENT STATE provided — never slugs you invented this pass.\n"
    "- The STANCE is her editorial read of the experiment and its claims (what she "
    "believes, what she's skeptical of). 'how_my_stance_changed' must describe a "
    "REAL evolution and every change needs receipts — short quotes or observations "
    "FROM THIS INSTALLMENT that justify it. If nothing genuinely changed, return an "
    "empty string and an empty receipts list.\n"
    "- The stance speaks to THINKING — never cite raw physiological numbers "
    "(no HRV/RHR/weights/percentages). Name the pattern, not the number.\n"
    "- Third person is wrong: Elena's notebook is first person ('I').\n\n"
    "## OUTPUT — ONLY valid JSON, no markdown, no preamble:\n"
    "{\n"
    '  "threads_opened": [{"slug": "kebab-case", "summary": "one line", "type": "pattern|question|conflict"}],\n'
    '  "threads_advanced": ["existing-slug"],\n'
    '  "threads_resolved": [{"slug": "existing-slug", "resolution": "one line"}],\n'
    '  "callbacks_made": [{"slug": "kebab-case", "promise": "what she promised readers", "due_in_weeks": 3}],\n'
    '  "callbacks_paid": [{"slug": "existing-slug", "payoff_note": "how this installment paid it off"}],\n'
    '  "motifs": ["running motif phrases actually used in this installment"],\n'
    '  "stance": {\n'
    '    "headline_stance": "one tight paragraph: my current editorial read of this experiment",\n'
    '    "positions": ["specific positions I currently hold"],\n'
    '    "how_my_stance_changed": "the genuine evolution vs my prior stance, or \\"\\"",\n'
    '    "receipts": ["short quotes/observations from THIS installment backing any change"]\n'
    "  }\n"
    "}\n"
)


def _call_haiku(system, user_message, max_tokens=2500, temperature=0.2):
    """Haiku via the shared Bedrock retry path. Returns dict or raw text."""
    body = {
        "model": AI_MODEL_HAIKU,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    from retry_utils import call_anthropic_raw

    resp = call_anthropic_raw(req)
    text = resp["content"][0]["text"].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# State gathering
# ══════════════════════════════════════════════════════════════════════════════


def gather_state():
    """Current Elena state, bounded: open threads, pending callbacks, motifs, stance."""
    threads = [t for t in _query_prefix(PERSONA_PK, "THREAD#") if t.get("status") == "open"]
    threads.sort(key=lambda t: int(t.get("last_referenced_week") or 0), reverse=True)
    callbacks = [c for c in _query_prefix(PERSONA_PK, "CALLBACK#") if c.get("status") == "pending"]
    callbacks.sort(key=lambda c: int(c.get("due_by_week") or 0))
    motif_state = _get_item(PERSONA_PK, "MOTIF#state") or {}
    stance = _get_item(PERSONA_PK, "STANCE#latest")
    return {
        "open_threads": threads[:MAX_OPEN_THREADS],
        "pending_callbacks": callbacks[:MAX_PENDING_CALLBACKS],
        "motifs": (motif_state.get("motifs") or [])[:MAX_MOTIFS],
        "stance": stance,
    }


def _build_extraction_message(installment_md, title, week_number, state):
    grounding = {
        "current_week": week_number,
        "open_threads": [
            {"slug": t.get("slug"), "summary": t.get("summary"), "opened_week": t.get("opened_week")} for t in state["open_threads"]
        ],
        "pending_callbacks": [
            {"slug": c.get("slug"), "promise": c.get("promise"), "made_in_week": c.get("made_in_week"), "due_by_week": c.get("due_by_week")}
            for c in state["pending_callbacks"]
        ],
        "running_motifs": [m.get("phrase") if isinstance(m, dict) else m for m in state["motifs"]],
        "previous_stance": (
            {
                "headline_stance": state["stance"].get("headline_stance", ""),
                "positions": state["stance"].get("positions", []),
                "as_of": state["stance"].get("as_of"),
            }
            if state["stance"]
            else None
        ),
    }
    body = installment_md or ""
    if len(body) > MAX_INSTALLMENT_CHARS:
        body = body[:MAX_INSTALLMENT_CHARS] + "\n[...truncated...]"
    return (
        f"## CURRENT STATE (Elena's notebook before this installment)\n"
        f"{json.dumps(grounding, indent=2, default=str)}\n\n"
        f'## THE JUST-PUBLISHED INSTALLMENT — Week {week_number}: "{title}"\n\n{body}\n\n'
        "Update Elena's notebook from this installment. Remember: resolved/paid slugs "
        "must come from CURRENT STATE; empty string for an unchanged stance."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic application (the LLM proposes, this code disposes)
# ══════════════════════════════════════════════════════════════════════════════


def _vital_hits(stance):
    if not isinstance(stance, dict):
        return 0
    prose = " ".join(
        [
            str(stance.get("headline_stance", "")),
            str(stance.get("how_my_stance_changed", "")),
            " ".join(str(x) for x in stance.get("positions", []) or []),
        ]
    )
    return len(_RAW_VITAL_RE.findall(prose))


def _sanitize_stance(stance, prior_stance):
    """The coach-stance discipline applied to Elena: no prior stance => no change
    is possible; a change claim without receipts is narrative invention — drop it."""
    if prior_stance is None:
        stance["how_my_stance_changed"] = ""
        stance["receipts"] = []
        return stance
    changed = stance.get("how_my_stance_changed") or ""
    receipts = [str(r).strip()[:200] for r in (stance.get("receipts") or []) if str(r).strip()]
    if changed and _CHANGE_RE.search(changed) and not receipts:
        logger.info("[elena-stance] dropping ungrounded evolution claim (no receipts)")
        stance["how_my_stance_changed"] = ""
    stance["receipts"] = receipts
    return stance


def apply_extraction(extraction, date_str, week_number, state):
    """Write the extraction into PERSONA#elena. Returns a summary dict."""
    now_iso = datetime.now(timezone.utc).isoformat()
    summary = {"threads_opened": 0, "threads_advanced": 0, "threads_resolved": 0, "callbacks_made": 0, "callbacks_paid": 0}
    open_by_slug = {t.get("slug"): t for t in state["open_threads"]}
    pending_by_slug = {c.get("slug"): c for c in state["pending_callbacks"]}

    # Threads opened
    for t in (extraction.get("threads_opened") or [])[:6]:
        slug = _slugify(t.get("slug") or t.get("summary"))
        if slug in open_by_slug:
            continue  # already open — treat as advanced below at most
        table.put_item(
            Item={
                "pk": PERSONA_PK,
                "sk": f"THREAD#{date_str}#{slug}",
                "slug": slug,
                "status": "open",
                "type": str(t.get("type") or "pattern")[:20],
                "summary": str(t.get("summary") or "")[:300],
                "opened_week": week_number,
                "last_referenced_week": week_number,
                "reference_count": 1,
                "created_at": now_iso,
            }
        )
        summary["threads_opened"] += 1

    # Threads advanced (bump the aging clock)
    for slug in (extraction.get("threads_advanced") or [])[:10]:
        rec = open_by_slug.get(_slugify(slug))
        if not rec:
            continue
        table.update_item(
            Key={"pk": PERSONA_PK, "sk": rec["sk"]},
            UpdateExpression="SET last_referenced_week = :w, reference_count = if_not_exists(reference_count, :z) + :one",
            ExpressionAttributeValues={":w": week_number, ":z": 0, ":one": 1},
        )
        summary["threads_advanced"] += 1

    # Threads resolved
    for r in (extraction.get("threads_resolved") or [])[:10]:
        rec = open_by_slug.get(_slugify(r.get("slug")))
        if not rec:
            continue
        table.update_item(
            Key={"pk": PERSONA_PK, "sk": rec["sk"]},
            UpdateExpression="SET #s = :resolved, resolution = :res, resolved_week = :w",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":resolved": "resolved", ":res": str(r.get("resolution") or "")[:300], ":w": week_number},
        )
        summary["threads_resolved"] += 1

    # Callbacks made (promises to readers — the ledger the prompt will enforce)
    for c in (extraction.get("callbacks_made") or [])[:4]:
        slug = _slugify(c.get("slug") or c.get("promise"))
        if slug in pending_by_slug:
            continue
        raw_due = c.get("due_in_weeks")
        try:
            due_in = int(raw_due) if raw_due is not None else DEFAULT_CALLBACK_DUE_WEEKS
        except (TypeError, ValueError):
            due_in = DEFAULT_CALLBACK_DUE_WEEKS
        due_in = max(MIN_CALLBACK_DUE_WEEKS, min(MAX_CALLBACK_DUE_WEEKS, due_in))
        table.put_item(
            Item={
                "pk": PERSONA_PK,
                "sk": f"CALLBACK#{date_str}#{slug}",
                "slug": slug,
                "status": "pending",
                "promise": str(c.get("promise") or "")[:300],
                "made_in_week": week_number,
                "due_by_week": week_number + due_in,
                "created_at": now_iso,
            }
        )
        summary["callbacks_made"] += 1

    # Callbacks paid
    for cp in (extraction.get("callbacks_paid") or [])[:8]:
        rec = pending_by_slug.get(_slugify(cp.get("slug")))
        if not rec:
            continue
        table.update_item(
            Key={"pk": PERSONA_PK, "sk": rec["sk"]},
            UpdateExpression="SET #s = :paid, payoff_note = :note, paid_in_week = :w",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":paid": "paid", ":note": str(cp.get("payoff_note") or "")[:300], ":w": week_number},
        )
        summary["callbacks_paid"] += 1

    # Motifs — merge, count repeats, keep the newest MAX_MOTIFS
    existing = {}
    for m in state["motifs"]:
        if isinstance(m, dict) and m.get("phrase"):
            existing[m["phrase"].lower()] = dict(m)
        elif isinstance(m, str) and m.strip():
            existing[m.strip().lower()] = {"phrase": m.strip(), "first_week": week_number, "count": 1}
    for phrase in (extraction.get("motifs") or [])[:6]:
        phrase = str(phrase).strip()[:120]
        if not phrase:
            continue
        key = phrase.lower()
        if key in existing:
            existing[key]["count"] = int(existing[key].get("count") or 1) + 1
            existing[key]["last_week"] = week_number
        else:
            existing[key] = {"phrase": phrase, "first_week": week_number, "last_week": week_number, "count": 1}
    motifs = sorted(existing.values(), key=lambda m: (int(m.get("last_week") or m.get("first_week") or 0)), reverse=True)[:MAX_MOTIFS]
    table.put_item(Item={"pk": PERSONA_PK, "sk": "MOTIF#state", "motifs": motifs, "last_updated": now_iso})
    summary["motifs"] = len(motifs)

    # Stance — with receipts, sanitized, vitals-flagged (grounding_flag readers skip)
    stance = extraction.get("stance") or {}
    if isinstance(stance, dict) and str(stance.get("headline_stance") or "").strip():
        stance = {
            "headline_stance": str(stance.get("headline_stance") or "")[:800],
            "positions": [str(p).strip()[:200] for p in (stance.get("positions") or [])[:6] if str(p).strip()],
            "how_my_stance_changed": str(stance.get("how_my_stance_changed") or "")[:400],
            "receipts": stance.get("receipts") or [],
        }
        _sanitize_stance(stance, state["stance"])
        stance_item = {
            "pk": PERSONA_PK,
            "sk": f"STANCE#{date_str}",
            "persona_id": "elena_voss",
            "as_of": date_str,
            "week_number": week_number,
            "generated_at": now_iso,
            "grounding_flag": _vital_hits(stance) > 0,
            **stance,
        }
        table.put_item(Item=stance_item)
        table.put_item(Item={**stance_item, "sk": "STANCE#latest"})
        summary["stance_written"] = True
        summary["stance_evolved"] = bool(stance.get("how_my_stance_changed"))
        summary["stance_grounding_flag"] = stance_item["grounding_flag"]
        if stance_item["grounding_flag"]:
            logger.warning("[elena-stance] stance cites raw vitals — flagged (consumers skip flagged stances)")
    else:
        summary["stance_written"] = False

    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════════════════════


def lambda_handler(event, context):
    """Post-publish state extraction for the Elena Voss persona (#537).

    Event: {"date": "YYYY-MM-DD"} — the published chronicle's DATE# key.
    Fail-soft everywhere: a skipped run just means her notebook ages a week.
    """
    try:
        date_str = (event or {}).get("date")
        if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_str)):
            return {"statusCode": 400, "error": "event.date (YYYY-MM-DD) required"}

        # Budget: pauses with the other narrative features (tier >= 1).
        try:
            import budget_guard

            if not budget_guard.allow("coach_narrative"):
                logger.info("[elena-state] budget tier pauses narrative extraction — skipping")
                return {"statusCode": 200, "skipped": "budget_tier"}
        except ImportError:
            pass

        installment = _get_item(CHRONICLE_PK, f"DATE#{date_str}", consistent=True)
        if not installment:
            return {"statusCode": 404, "error": f"no chronicle record for {date_str}"}
        if installment.get("status") != "published":
            # Never learn from a draft — a rejected draft must not poison memory.
            return {"statusCode": 200, "skipped": f"status={installment.get('status')}"}

        content_md = installment.get("content_markdown") or ""
        title = installment.get("title") or "Untitled"
        try:
            week_number = int(installment.get("week_number") or 0)
        except (TypeError, ValueError):
            week_number = 0
        if not content_md or week_number <= 0:
            return {"statusCode": 200, "skipped": "no content or week number"}

        state = gather_state()
        extraction = _call_haiku(
            system=EXTRACTION_SYSTEM_PROMPT,
            user_message=_build_extraction_message(content_md, title, week_number, state),
        )
        if not isinstance(extraction, dict):
            logger.warning("[elena-state] extraction returned non-dict — nothing written")
            return {"statusCode": 200, "skipped": "extraction_failed"}

        summary = apply_extraction(extraction, date_str, week_number, state)
        logger.info("[elena-state] week %s applied: %s", week_number, json.dumps(summary))
        return {"statusCode": 200, "week_number": week_number, **summary}

    except Exception as e:
        logger.error("[elena-state] failed (fail-soft — memory ages a week): %s", e, exc_info=True)
        return {"statusCode": 500, "error": str(e)}
