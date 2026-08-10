"""conversation_enrichment.py — conversational capture becomes numeric signal (#1577, epic #1476).

The survey-confirmed gap: coach check-in answers (#915), habit reflections (#422) and
field-note responses (BL-04) are stored verbatim and folded into coach episodic memory —
but they never become numeric inputs to flourishing/character/hypotheses the way enriched
journal text does. This module closes that loop by riding the SAME journal enrichment
path (the #1572 "no second pipeline" principle, exactly like social_enrichment #1671):
a lean subset of the journal-enrichment schema is extracted ONCE per conversational
record by Haiku, the SAME deterministic ADR-104 grounding gate verifies every causal
hint, and the ``enriched_*`` fields are written IN PLACE onto the source record.

The conversational channels (channel provenance stamped on every output row):

  coach_checkin      pk COACH#{coach_id}_coach          sk CHECKIN#{date}#{uuid8}
                     (status=answered only — a skip is a boundary, never data, ADR-104)
  prescription_      pk COACH#{coach_id}_coach          sk CHECKIN#{date}#{uuid8}
    reaction         (#1708: the SAME partition — a check-in generated_by
                     "prescription_followup", i.e. Matthew reacting to the coach's
                     weekly Horizons pick. Same sweep, same gate, distinct channel.)
  habit_reflection   pk USER#{u}#SOURCE#habit_causality sk HABITDAY#{date}#{slug}
                     (channel=claude_reflection rows — the #422 Claude-sourced layer)
  field_note         pk USER#{u}#SOURCE#field_notes     sk WEEK#{iso-week}
                     (rows where Matthew has written matthew_notes back)

SCOPE — ANALYSIS-ONLY v1 (ADR-104/105, the #1577 AC2 recommendation, adopted):
``enrichment_policy()`` is the single declared scope. Conversational signals seed
HYPO_CANDIDATE# rows (via journal_analyzer) and are visible wherever enriched fields are
read, but they do NOT feed character or flourishing scoring — no SOURCE#flourishing row
is ever written from a conversational record, and character_engine reads none of these
partitions. Promotion to scoring requires personal-variance thresholds derived from an
observed baseline FIRST (ADR-105) and a Methods Registry re-review; the registry entry
(lambdas/methods_registry.py, "conversational_enrichment_scope") fingerprints the policy
function so that promotion cannot happen silently.

Double-counting guard (#1577 AC4): a takeaway routed into BOTH Notion and a check-in
(e.g. a vlog-close takeaway) must not enrich twice. Deterministic rule, no LLM:
whitespace/case-normalized content-hash equality, or ≥DEDUP_MIN_CHARS normalized
containment against the journal corpus of the window (padded ±JOURNAL_DEDUP_PAD_DAYS),
or a hash collision with any other conversational record already enriched/seen. Deduped
records are stamped (``enrichment_deduped_at``) so they are never re-attempted.

Cost: Haiku only (model tiering ADR-049), ~a few short calls/day. Budget-gated as
``conversation_enrichment`` — band 1 INTERNAL in lambdas/budget_guard.py (ADR-125:
analysis-layer AI pauses first, before anything a reader reads). A paused run returns an
explicit ``paused_by_budget`` status, never silent.

Runs from journal_enrichment_lambda's handler on the existing 6:30 AM PT cadence
(cron(30 14) UTC) — deliberately NOT a new Lambda. Pure at import: no AWS clients are
created until run() executes, so methods_registry (and tests) can import this module
without credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

# ── Channels (the #1577 provenance vocabulary) ────────────────────────────────
CHANNEL_COACH_CHECKIN = "coach_checkin"
CHANNEL_HABIT_REFLECTION = "habit_reflection"
CHANNEL_FIELD_NOTE = "field_note"
# #1708 (epic #1686 S4): a reaction to the coach's weekly Horizons pick arrives as a
# CHECKIN# row too, but it is a distinct capture channel — the reader reacting to
# something the coach sent OUTWARD, not answering a question about his own data. It
# gets its own channel value (the same idiom as journal's video_diary /
# solo_recording, #1572/#1840) so the Mind-pillar and coach-signal consumers can see
# WHERE the signal came from. Same partition, same sweep, same gate: no new pipeline.
CHANNEL_PRESCRIPTION_REACTION = "prescription_reaction"
CHANNELS = (CHANNEL_COACH_CHECKIN, CHANNEL_HABIT_REFLECTION, CHANNEL_FIELD_NOTE, CHANNEL_PRESCRIPTION_REACTION)

SCHEMA_VERSION = 1
# Conversational answers are shorter than journal entries; the floor is words (the J-5
# lesson) but lower than the journal's 20 — an 8-word check-in answer can carry a real
# barrier/context signal, below that the extraction is only noise.
MIN_TEXT_WORDS = 8
# AC4 containment floor: a ≥40-char verbatim (normalized) overlap with a journal entry
# is a routed takeaway, not coincidence.
DEDUP_MIN_CHARS = 40
JOURNAL_DEDUP_PAD_DAYS = 3
# Field notes are weekly and check-ins are answered on Matthew's schedule, so the
# default sweep window is wider than the journal's 2 days; already-enriched records
# skip, so the wide window costs reads, not Haiku calls.
DEFAULT_LOOKBACK_DAYS = 14

BUDGET_FEATURE = "conversation_enrichment"

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5-20251001")

# Fallback coach roster if persona_registry is unavailable (mirrors the
# coach_checkin FALLBACK_QUESTIONS domains) — collection must fail soft, never hard.
# #2334 roster-copy waiver: a fail-soft LITERAL is this constant's whole point
# (deriving it would fail with the registry); asserted equal to
# OPERATIONAL_SHORT_IDS by tests/test_coach_roster_set_guard_2334.py.
_FALLBACK_COACH_IDS = ("sleep", "nutrition", "mind", "physical", "glucose", "labs", "explorer")


# ── Scope policy (fingerprinted by the Methods Registry — do not edit casually) ──


def enrichment_policy():
    """The declared scope of conversational enrichment signals (#1577 AC2).

    ANALYSIS-ONLY v1: conversational signals seed hypothesis candidates and are
    visible as enriched context, but they do NOT move character or flourishing
    scoring. This function is fingerprinted by the Methods Registry entry
    ``conversational_enrichment_scope`` — changing the scope here without a human
    re-review of that entry (and, for any scoring promotion, personal-variance
    thresholds per ADR-105) fails tests/test_methods_registry.py.

    #1708 added a FOURTH channel (``prescription_reaction`` — a reaction to the
    weekly Horizons pick, captured on the same CHECKIN# partition). It inherits this
    same analysis-only scope: it seeds hypothesis candidates and calibrates the
    deterministic Horizons ledger, and it moves no scoring.
    """
    return {
        "scope": "analysis_only",
        "channels": list(CHANNELS),
        "seeds_hypothesis_candidates": True,
        "moves_character_scoring": False,
        "moves_flourishing_scoring": False,
        "min_text_words": MIN_TEXT_WORDS,
        "dedup": "content-hash equality, or >=40-char normalized containment vs the journal corpus (AC4)",
        "model_tier": "haiku",
        "budget_feature": BUDGET_FEATURE,
    }


# ── Deterministic text helpers ────────────────────────────────────────────────


def normalize_text(text) -> str:
    """Whitespace-collapsed, lowercased form used for hashing and containment."""
    return " ".join(str(text or "").split()).lower()


def content_hash(text) -> str:
    """Stable 16-hex content hash of the normalized text (the AC4 dedup key)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def is_duplicate_takeaway(text, journal_texts) -> bool:
    """AC4 dedup rule (deterministic, no LLM): True when `text` already lives in the
    journal corpus — hash-equal to an entry, or a ≥DEDUP_MIN_CHARS normalized
    substring of one (the vlog-close takeaway pasted into Notion AND spoken to a
    check-in). Short texts dedup only by hash equality — containment on a tiny
    string would false-positive."""
    norm = normalize_text(text)
    if not norm:
        return False
    h = content_hash(text)
    for jt in journal_texts or []:
        njt = normalize_text(jt)
        if not njt:
            continue
        if h == content_hash(jt):
            return True
        if len(norm) >= DEDUP_MIN_CHARS and norm in njt:
            return True
    return False


def week_monday(week: str):
    """ISO week 'YYYY-WNN' → its Monday as 'YYYY-MM-DD' (the field-note row date);
    None on a malformed week."""
    try:
        return datetime.strptime(f"{week}-1", "%G-W%V-%u").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# ── Per-channel enrichable text (grounding runs against EXACTLY this text) ───


def checkin_text(item) -> str:
    """The verbatim answer — the question is prompt CONTEXT, never grounded against."""
    return str(item.get("answer") or "").strip()


def habit_reflection_text(item) -> str:
    """The reflection fields, labeled, in a stable order — verbatim content."""
    parts = []
    for field, label in (("trigger", "trigger"), ("reward", "reward"), ("why_missed", "why it was missed"), ("context", "context")):
        val = str(item.get(field) or "").strip()
        if val:
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def field_note_text(item) -> str:
    """Matthew's right-page response: notes + anything he added."""
    parts = [str(item.get("matthew_notes") or "").strip(), str(item.get("matthew_added") or "").strip()]
    return "\n".join(p for p in parts if p)


def checkin_channel(item) -> str:
    """The channel a CHECKIN# row belongs to (#1708).

    A follow-up on the coach's weekly Horizons pick is stamped
    ``generated_by="prescription_followup"`` by
    ``coach_checkin.build_prescription_followup_item``; everything else on the
    partition is an ordinary check-in. Delegates the predicate to the reading rail
    so the marker literal lives in exactly one place.
    """
    try:
        from reading import horizons_calibration

        if horizons_calibration.is_prescription_reaction(item):
            return CHANNEL_PRESCRIPTION_REACTION
    except ImportError:  # pragma: no cover — bundled package; degrade to the base channel
        logger.warning("[#1708] reading package unavailable — check-in channel falls back to %s", CHANNEL_COACH_CHECKIN)
    return CHANNEL_COACH_CHECKIN


def conversation_context(item, channel) -> str:
    """One line of situational context for the prompt (never enrichable text)."""
    if channel == CHANNEL_PRESCRIPTION_REACTION:
        who = item.get("coach_name") or item.get("coach_id") or "a coach"
        week = item.get("prescription_week") or "?"
        return f"His coach ({who}) sent him the week-{week} Horizons media pick and asked: " f'"{str(item.get("question") or "").strip()}"'
    if channel == CHANNEL_COACH_CHECKIN:
        who = item.get("coach_name") or item.get("coach_id") or "a coach"
        return f'His coach ({who}) asked: "{str(item.get("question") or "").strip()}"'
    if channel == CHANNEL_HABIT_REFLECTION:
        return f"Reflection about the habit '{item.get('habit') or item.get('slug') or '?'}'"
    if channel == CHANNEL_FIELD_NOTE:
        agreement = item.get("matthew_agreement")
        base = f"His written response to the week {item.get('week') or '?'} AI lab notes"
        return f"{base} (stated agreement: {agreement})" if agreement else base
    return ""


# ── Collection (one query per partition family; fail-soft per family) ────────


def _query_between(table, pk, sk_lo, sk_hi):
    """Paginated Key-condition query pk + sk BETWEEN [sk_lo, sk_hi].

    ADR-077/phase_filter.py contract: every read of platform DDB data passes
    through with_phase_filter() — this is the SINGLE query helper for all
    three conversational partitions plus the journal dedup corpus, so wiring
    it here closes the gap module-wide in one place (#1790). Two of the three
    conversational source families are EXPERIMENT_SCOPED (field_notes,
    coach_checkin via the COACH#* rule) and the 14-day rolling lookback can
    reach across a genesis into the wiped prior cycle; without this, a
    tombstoned row would be enriched and its `enriched_*` fields would seed
    new-cycle hypotheses from conversation the reset declared erased."""
    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import with_phase_filter

    kwargs = with_phase_filter({"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(sk_lo, sk_hi)})
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _coach_ids():
    try:
        from coach.persona_registry import OPERATIONAL_SHORT_IDS

        return list(OPERATIONAL_SHORT_IDS)
    except Exception as e:  # noqa: BLE001 — collection fails soft, never hard
        logger.warning("[#1577] persona_registry unavailable (%s) — using fallback roster", type(e).__name__)
        return list(_FALLBACK_COACH_IDS)


def _sk_date(sk, prefix):
    m = re.match(rf"^{prefix}(\d{{4}}-\d{{2}}-\d{{2}})", str(sk or ""))
    return m.group(1) if m else None


def collect_conversational_items(table, start_date, end_date, coach_ids=None):
    """All candidate conversational records in [start_date, end_date], as
    [{"item", "channel", "text", "date", "context"}], sorted (date, channel, sk) so
    dedup precedence is deterministic. Each partition family fails soft."""
    out = []

    # 1. Coach check-ins — answered only (a skip is a boundary, not data; ADR-104).
    for cid in coach_ids if coach_ids is not None else _coach_ids():
        cid = str(cid).removesuffix("_coach")
        try:
            rows = _query_between(table, f"COACH#{cid}_coach", f"CHECKIN#{start_date}", f"CHECKIN#{end_date}#~")
        except Exception as e:  # noqa: BLE001
            logger.warning("[#1577] check-in query failed for %s: %s", cid, e)
            continue
        for it in rows:
            if it.get("status") != "answered":
                continue
            text = checkin_text(it)
            if not text:
                continue
            date = _sk_date(it.get("sk"), "CHECKIN#") or (it.get("answered_at") or "")[:10]
            channel = checkin_channel(it)  # #1708: prescription_reaction vs plain coach_checkin
            out.append(
                {
                    "item": it,
                    "channel": channel,
                    "text": text,
                    "date": date,
                    "context": conversation_context(it, channel),
                }
            )

    # 2. Habit reflections — the #422 claude_reflection channel only (Habitify in-app
    #    notes are typed telemetry, not the conversational corpus this issue names).
    try:
        rows = _query_between(table, f"USER#{USER_ID}#SOURCE#habit_causality", f"HABITDAY#{start_date}", f"HABITDAY#{end_date}~")
        for it in rows:
            if it.get("channel") != "claude_reflection":
                continue
            text = habit_reflection_text(it)
            if not text:
                continue
            date = it.get("date") or _sk_date(it.get("sk"), "HABITDAY#")
            out.append(
                {
                    "item": it,
                    "channel": CHANNEL_HABIT_REFLECTION,
                    "text": text,
                    "date": date,
                    "context": conversation_context(it, CHANNEL_HABIT_REFLECTION),
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[#1577] habit reflection query failed: %s", e)

    # 3. Field-note responses — WEEK# rows where Matthew has written back.
    try:
        y0, w0, _ = datetime.strptime(start_date, "%Y-%m-%d").isocalendar()
        y1, w1, _ = datetime.strptime(end_date, "%Y-%m-%d").isocalendar()
        rows = _query_between(table, f"USER#{USER_ID}#SOURCE#field_notes", f"WEEK#{y0}-W{w0:02d}", f"WEEK#{y1}-W{w1:02d}~")
        for it in rows:
            text = field_note_text(it)
            if not text:
                continue
            date = week_monday(str(it.get("week") or str(it.get("sk", "")).replace("WEEK#", ""))) or start_date
            out.append(
                {
                    "item": it,
                    "channel": CHANNEL_FIELD_NOTE,
                    "text": text,
                    "date": date,
                    "context": conversation_context(it, CHANNEL_FIELD_NOTE),
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[#1577] field-note query failed: %s", e)

    out.sort(key=lambda c: (c["date"] or "", c["channel"], str(c["item"].get("sk", ""))))
    return out


def fetch_journal_texts(table, start_date, end_date):
    """raw_text of the notion journal entries in the (padded) window — the AC4
    dedup corpus. Fail-soft to [] (no corpus ⇒ no journal dedup, never a crash)."""
    try:
        rows = _query_between(table, f"USER#{USER_ID}#SOURCE#notion", f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~")
        return [str(i.get("raw_text") or "") for i in rows if "#journal#" in str(i.get("sk", "")) and i.get("raw_text")]
    except Exception as e:  # noqa: BLE001
        logger.warning("[#1577] journal dedup corpus unavailable: %s", e)
        return []


# ── Haiku extraction (lean subset of the journal schema) ─────────────────────

SYSTEM_PROMPT = """You are an expert behavioral analyst reading a SHORT conversational answer Matthew gave on his personal health platform (a coach check-in answer, a habit reflection, or a written response to weekly lab notes). Extract structured signals from HIS OWN WORDS. Be precise — only flag what's clearly present, never infer what isn't there.

Rules:
- Be conservative. The text is short; most fields will be null or empty. That is the correct answer.
- Scores: only rate what the text itself supports; null when unclear.
- emotions: precise terms ("apprehensive" over "bad"). Max 4.
- themes: life themes, max 4, ordered by prominence.
- avoidance_flags: things being avoided/procrastinated/feared. Empty list if none.
- causal_hints: ONLY cause→effect links the author EXPLICITLY asserts ("X because Y", "Y so X"). NEVER infer a link yourself. The quote must be the verbatim sentence from the ANSWER TEXT that asserts the link — copy it exactly, character for character. Never quote the question or the context line.
- Respond with ONLY valid JSON. No preamble, no markdown fences, no explanation."""

USER_PROMPT_TEMPLATE = """CONVERSATIONAL ANSWER (channel: {channel}):
{text}

CONTEXT (not part of the answer — never quote from it):
- Date: {date}
- {context}

Extract as JSON:
{{
  "mood_score": <1-5 synthesized from mood signals in the answer, null if unclear>,
  "energy_score": <1-5, null if unclear>,
  "stress_score": <1-5 (1=calm, 5=overwhelmed), null if unclear>,
  "sentiment": <"positive"|"neutral"|"negative"|"mixed">,
  "emotions": [<precise emotional vocabulary, max 4. Empty list if the text is too thin>],
  "themes": [<life themes, max 4, most prominent first. Empty list if none>],
  "avoidance_flags": [<things being avoided/procrastinated/feared. Empty list if none>],
  "causal_hints": [<cause->effect links the author EXPLICITLY asserts, each {{"cause": "...", "effect": "...", "quote": "<verbatim sentence from the answer>"}}. Max 3. Empty list if none — most answers have none>]
}}"""


def build_prompt(text, channel, date, context):
    """The Anthropic Messages body (Haiku — structured task, ADR-049)."""
    return {
        "model": MODEL,
        "max_tokens": 700,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text, channel=channel, date=date, context=context or "(none)")}
        ],
    }


def parse_extraction(result):
    """Model response → dict (fence-tolerant), or None on unparseable output."""
    text = "".join(b.get("text", "") for b in (result or {}).get("content", []) if b.get("type") == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("[#1577] failed to parse extraction: %s — raw: %.300s", e, text)
        return None


def _ground_causal_hints(hints, text):
    """The ONE ADR-104 grounding gate — reused from the journal enricher (exactly as
    social_enrichment does), lazily so this module stays pure at import."""
    from ingestion.journal_enrichment_lambda import _ground_causal_hints as _gch

    return _gch(hints, text)


# Extraction key → (dynamo attribute, type). Same enriched_* names as the journal
# schema so any consumer of enriched fields reads conversational rows uniformly.
FIELD_MAPPING = {
    "mood_score": ("enriched_mood", "N"),
    "energy_score": ("enriched_energy", "N"),
    "stress_score": ("enriched_stress", "N"),
    "sentiment": ("enriched_sentiment", "S"),
    "emotions": ("enriched_emotions", "L"),
    "themes": ("enriched_themes", "L"),
    "avoidance_flags": ("enriched_avoidance_flags", "L"),
    "causal_hints": ("enriched_causal_hints", "L"),  # list of {cause, effect, quote}
}


#  ADR-077 (#1790): a defense-in-depth belt on top of the phase-filtered read —
#  the write itself must refuse to land on a row that has since been
#  tombstoned (a reset can run between collection and the Haiku round-trip).
#  Mirrors singleton_visible's tombstone predicate as a DDB condition.
_NOT_TOMBSTONED_CONDITION = "attribute_not_exists(tombstone) OR tombstone = :ce_not_tombstoned"
_NOT_TOMBSTONED_VALUE = {":ce_not_tombstoned": False}


def apply_enrichment(table, item, channel, enrichment, text):
    """Write the enriched_* fields IN PLACE onto the conversational record, with the
    #1577 provenance stamps: enriched_channel (AC1), enriched_scope (AC2 —
    analysis_only), enriched_content_hash (AC4), enriched_at + schema version.
    Grounding gate runs BEFORE anything is written. Returns True when written,
    False when the write was refused because the row is now tombstoned
    (ADR-077, #1790) — the caller must not count that as an enrichment."""
    if enrichment.get("causal_hints"):
        kept, dropped = _ground_causal_hints(enrichment["causal_hints"], text)
        enrichment["causal_hints"] = kept
        if dropped:
            logger.info("[#1577] grounding gate dropped %d ungrounded hint(s) for %s", dropped, item.get("sk"))

    update_parts, attr_names, attr_values = [], {}, {}
    for key, (dynamo_key, dtype) in FIELD_MAPPING.items():
        val = enrichment.get(key)
        if val is None or (isinstance(val, list) and not val):
            continue
        alias, placeholder = f"#{dynamo_key}", f":{dynamo_key}"
        attr_names[alias] = dynamo_key
        if dtype == "N":
            attr_values[placeholder] = Decimal(str(val))
        elif dtype == "S":
            attr_values[placeholder] = str(val)
        else:
            attr_values[placeholder] = val
        update_parts.append(f"{alias} = {placeholder}")

    stamps = {
        "enriched_channel": str(channel),
        "enriched_scope": enrichment_policy()["scope"],
        "enriched_content_hash": content_hash(text),
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }
    # #1708: a Horizons reaction carries WHICH pick it is about, so a Mind-pillar or
    # coach-signal consumer reading the enriched row can attribute the signal without
    # re-joining to the check-in's generation metadata.
    if channel == CHANNEL_PRESCRIPTION_REACTION:
        for stamp_key, source_key in (
            ("enriched_prescription_week", "prescription_week"),
            ("enriched_prescription_curator", "prescription_curator"),
        ):
            value = str(item.get(source_key) or "").strip()
            if value:
                stamps[stamp_key] = value
    for name, value in stamps.items():
        attr_names[f"#{name}"] = name
        attr_values[f":{name}"] = value
        update_parts.append(f"#{name} = :{name}")
    attr_names["#esv"] = "enriched_schema_version"
    attr_values[":esv"] = Decimal(SCHEMA_VERSION)
    update_parts.append("#esv = :esv")
    attr_values.update(_NOT_TOMBSTONED_VALUE)

    from botocore.exceptions import ClientError

    try:
        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET " + ", ".join(update_parts),
            ConditionExpression=_NOT_TOMBSTONED_CONDITION,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("[#1790] refused to enrich %s — tombstoned since collection (ADR-077)", item.get("sk"))
            return False
        raise
    return True


def mark_deduped(table, item, reason, text):
    """Stamp an AC4-deduped record so it is never re-attempted (and the routing
    decision is auditable). No enriched_at — the record is NOT enriched.
    Refuses the write onto a since-tombstoned row (ADR-077, #1790); returns
    False in that case so the caller doesn't count a phantom dedup."""
    from botocore.exceptions import ClientError

    try:
        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET enrichment_deduped_at = :ts, enrichment_dedup_reason = :r, enriched_content_hash = :h",
            ConditionExpression=_NOT_TOMBSTONED_CONDITION,
            ExpressionAttributeValues={
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":r": str(reason),
                ":h": content_hash(text),
                **_NOT_TOMBSTONED_VALUE,
            },
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("[#1790] refused to mark-deduped %s — tombstoned since collection (ADR-077)", item.get("sk"))
            return False
        raise
    return True


# ── The analyzer seam (#1577 AC3) ─────────────────────────────────────────────


def enriched_conversational_records(table, start_date, end_date, coach_ids=None):
    """(date, record, channel) triples for every ALREADY-ENRICHED conversational
    record in the window — journal_analyzer folds these into HYPO_CANDIDATE#
    aggregation so a hypothesis born from a check-in carries its channel."""
    return [
        (c["date"], c["item"], c["channel"])
        for c in collect_conversational_items(table, start_date, end_date, coach_ids=coach_ids)
        if c["item"].get("enriched_at")
    ]


# ── The sweep ─────────────────────────────────────────────────────────────────


def _call_haiku(body):
    from common.retry_utils import call_anthropic_raw  # lazy — bundled module, runtime only

    return call_anthropic_raw(body, timeout=30)


def run(table=None, start_date=None, end_date=None, force=False, caller=None, coach_ids=None):
    """One conversational-enrichment sweep. Returns a summary dict; never raises for
    a single bad record. Budget-gated: an over-tier run returns an explicit
    ``paused_by_budget`` status without a single Haiku call (AC1)."""
    from ai import budget_guard

    if not budget_guard.allow(BUDGET_FEATURE):
        tier = budget_guard.current_tier()
        logger.info("[#1577] conversation enrichment paused by budget tier %d", tier)
        return {"status": "paused_by_budget", "tier": tier, "enriched": 0, "skipped": 0, "deduped": 0, "errors": 0}

    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    if end_date is None:
        # #1964: was `timezone(timedelta(hours=-8))` — PST pinned year-round, an
        # hour off for the ~8 months of PDT and therefore capable of selecting the
        # wrong Pacific day. DST-aware via the canonical helper.
        from common.pacific_time import pacific_today

        end_date = pacific_today()
    if start_date is None:
        start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")

    pad = timedelta(days=JOURNAL_DEDUP_PAD_DAYS)
    corpus_start = (datetime.strptime(start_date, "%Y-%m-%d") - pad).strftime("%Y-%m-%d")
    corpus_end = (datetime.strptime(end_date, "%Y-%m-%d") + pad).strftime("%Y-%m-%d")
    journal_texts = fetch_journal_texts(table, corpus_start, corpus_end)

    candidates = collect_conversational_items(table, start_date, end_date, coach_ids=coach_ids)

    # Cross-channel/cross-run hash ledger: hashes of everything already enriched in
    # the window, so the SAME takeaway logged into two conversational channels
    # dedups even across runs (AC4).
    seen_hashes = {str(c["item"].get("enriched_content_hash")) for c in candidates if c["item"].get("enriched_content_hash")}

    enriched = skipped = deduped = errors = 0
    call = caller or _call_haiku
    for cand in candidates:
        item, channel, text = cand["item"], cand["channel"], cand["text"]
        sk = item.get("sk", "")

        if len(text.split()) < MIN_TEXT_WORDS:
            skipped += 1
            continue
        stale_schema = int(item.get("enriched_schema_version") or 0) < SCHEMA_VERSION
        if not force and item.get("enriched_at") and not stale_schema:
            skipped += 1
            continue
        if not force and item.get("enrichment_deduped_at"):
            skipped += 1
            continue

        h = content_hash(text)
        if not item.get("enriched_at"):  # an already-enriched record re-running (force/schema) keeps its slot
            if h in seen_hashes:
                if mark_deduped(table, item, "conversational_duplicate", text):
                    deduped += 1
                else:
                    skipped += 1  # tombstoned since collection (ADR-077, #1790)
                continue
            if is_duplicate_takeaway(text, journal_texts):
                if mark_deduped(table, item, "journal_duplicate", text):
                    deduped += 1
                else:
                    skipped += 1  # tombstoned since collection (ADR-077, #1790)
                continue
        seen_hashes.add(h)

        try:
            extraction = parse_extraction(call(build_prompt(text, channel, cand["date"], cand["context"])))
            if not extraction:
                errors += 1
                continue
            if apply_enrichment(table, item, channel, extraction, text):
                enriched += 1
                logger.info(
                    "[#1577] enriched %s (%s): sentiment=%s themes=%s hints=%d",
                    sk,
                    channel,
                    extraction.get("sentiment"),
                    extraction.get("themes"),
                    len(extraction.get("causal_hints") or []),
                )
            else:
                skipped += 1  # tombstoned since collection (ADR-077, #1790)
        except Exception as e:  # noqa: BLE001 — one bad record must not fail the sweep
            errors += 1
            logger.error("[#1577] error enriching %s: %s", sk, e)

    summary = {
        "status": "ok",
        "scope": enrichment_policy()["scope"],
        "candidates": len(candidates),
        "enriched": enriched,
        "skipped": skipped,
        "deduped": deduped,
        "errors": errors,
        "date_range": f"{start_date} → {end_date}",
    }
    logger.info("[#1577] conversational enrichment complete: %s", summary)
    return summary
