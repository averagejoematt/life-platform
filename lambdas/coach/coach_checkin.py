"""coach_checkin.py — the ad-hoc coach check-in loop (#915).

Matthew periodically talks to his AI coaches from Claude chat (via the MCP
server). A coach asks him up to 3 OPEN, autonomy-supportive questions; his
verbatim answers (or explicit skips) are stored and become the qualitative
context layer that pairs with — or explains the absence of — the quantitative
data. Mirrors the #422 habit-reflection idiom: a READ tool surfaces what to
ask (get_coach_checkin_queue), a WRITE tool records the answer verbatim
(log_coach_checkin). This module is the deterministic core shared by the MCP
tools and any future prompt consumers; the MCP surface lives in
mcp/tools_coach_checkin.py.

Store (single-table; same COACH# partition family as STANCE#/PREDICTION#/LEARNING#):
  pk = COACH#{coach_id}_coach            (evaluator convention — suffixed id)
  sk = CHECKIN#{YYYY-MM-DD}#{uuid8}

Fields: coach_id (bare, e.g. "mind"), coach_name, question, status
(open|answered|skipped), answer (verbatim — ADR-104, no paraphrase), skipped
(bool), tags, asked_at, answered_at, provenance="mcp", cycle (int — SSM
/life-platform/experiment-cycle at write time, fail-soft absent),
context_reason (why this coach asked), generated_by ("bedrock"|"fallback").

Behavioral rules (psychology panel, encoded in the generation prompt):
  * max 3 open questions at any time — never a backlog of guilt;
  * questions are open + autonomy-supportive ("what got in the way this
    week?"), NEVER compliance-audit phrasing ("did you take your supplements?");
  * the asking coach rotates toward the most informative current signal (the
    longest-dark manual channel), with a deterministic least-recently-asked
    rotation as the fallback;
  * the coach who asked last never wins the dark-channel preference again straight away,
    and an open question rotates out after QUEUE_ROTATE_HOURS or when its driving source is
    paused (status `retired`, never a skip) — the queue sat on three food-delivery questions
    for two weeks before this (#5127);
  * skip is always a valid answer with zero penalty;
  * when presence is dark, questions are about barriers/context — not guilt.

Phase taxonomy (ADR-077): these records SHOULD be cross_phase — qualitative
history is exactly what ought to survive an experiment reset. The one-line
registry addition in lambdas/phase_taxonomy.py is a deliberate follow-up
(another owner); until it lands, CHECKIN# rows inherit the COACH#* default
(experiment_scoped) — see the PR body for #915.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from common.pacific_time import pacific_now, pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

logger = logging.getLogger(__name__)

CHECKIN_SK_PREFIX = "CHECKIN#"
PROVENANCE = "mcp"
STATUS_OPEN = "open"
STATUS_ANSWERED = "answered"
STATUS_SKIPPED = "skipped"
# #5127: an open question the queue took down unanswered — its driving source is paused, or it
# sat past the rotation window. Never a skip and never a penalty: nobody declined anything, the
# question simply stopped being the right one to ask. `retired_code` + `retired_reason` record why.
STATUS_RETIRED = "retired"
RETIRED_SOURCE_PAUSED = "source_paused"
RETIRED_ROTATED = "rotated"

# #5127: the queue was stuck 2026-10-10 → 10-23 on three questions a dead source drove, because an
# open question never left. An open question now rotates out once it has stood this long, so the
# next coach gets the turn; a Horizons prescription follow-up keeps its week. The nightly
# `coach_checkin:queue_age` check (operational/coach_checkin_queue_qa.py) alarms when one did not.
QUEUE_ROTATE_HOURS = 72
PRESCRIPTION_ROTATE_HOURS = 7 * 24

MAX_OPEN_QUESTIONS = 3
MAX_QUESTION_CHARS = 300
MAX_ANSWER_CHARS = 4000

# Structured task → Haiku (model tiering, ADR-049); env-overridable.
from ai.model_routing import model_for  # noqa: E402 — #4770: the one model registry

MODEL = model_for("coach_checkin")

SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"

# Deterministic fallback bank — used when Bedrock is unavailable (budget tier 3,
# throttle, missing grant) so the loop degrades to a usable question rather than
# an error. All autonomy-supportive by construction.
FALLBACK_QUESTIONS = {
    "sleep": "How have the evenings before bed actually been feeling lately — what shapes when you wind down?",
    "nutrition": "What's been shaping how you eat this week — anything that made it easier or harder than usual?",
    "training": "How is training sitting with you right now — what feels good, and what's been getting in the way?",
    "mind": "What's been taking up the most mental space this week — and is any of it showing up in the data, or invisible to it?",
    "physical": "How does your body feel day-to-day lately — anything the measurements wouldn't show?",
    "glucose": "What's your relationship with the CGM been like recently — useful companion, background noise, or a chore?",
    "labs": "Since the last labs, is there anything you've changed — or been meaning to change — that we should know about?",
    "explorer": "If you could have this platform ask you about one thing it currently can't see, what would it be?",
}


# ── keys ─────────────────────────────────────────────────────────────────────


def normalize_coach_id(coach_id: str) -> str:
    """Bare coach id ('mind') from either the bare or the '_coach'-suffixed form."""
    cid = (coach_id or "").strip().lower()
    return cid.removesuffix("_coach")


def checkin_pk(coach_id: str) -> str:
    """The canonical COACH# partition (evaluator convention: '_coach' suffix)."""
    return f"COACH#{normalize_coach_id(coach_id)}_coach"


def new_checkin_sk(date_str: Optional[str] = None, uid: Optional[str] = None) -> str:
    d = date_str or pacific_today()
    return f"{CHECKIN_SK_PREFIX}{d}#{uid or uuid.uuid4().hex[:8]}"


def checkin_uid(*parts: object) -> str:
    """A deterministic 8-hex check-in uid derived from what makes the question the
    SAME question (#3114).

    The uuid4 default above is right for a coach's freshly generated question — two
    generations genuinely are two questions. It is wrong for a check-in that is a
    projection of another record: `curate_horizon`'s prescription follow-up is one
    question per (week, coach, type, text), and a replayed curate minted a second
    copy of it in the coach's queue for Matthew to answer twice."""
    canonical = "\x1f".join(" ".join(str("" if p is None else p).split()) for p in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def utcnow() -> datetime:
    """The one clock read in this module (tests freeze it here)."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value) -> Optional[datetime]:
    """An aware UTC datetime from a stored ISO stamp ('...Z' or '+00:00'); None when unreadable."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── The Coach's Prescription follow-up hook (#1706, epic #1686) ───────────────

FOLLOWUP_QUESTION = "question"
FOLLOWUP_HANDOFF = "handoff"
FOLLOWUP_TYPES = (FOLLOWUP_QUESTION, FOLLOWUP_HANDOFF)


def build_prescription_followup_item(
    week: str,
    curating_coach: str,
    follow_up: Optional[dict],
    *,
    cycle: Optional[int] = None,
    now: Optional[str] = None,
    coach_name_of=None,
) -> Optional[dict]:
    """Build ONE CHECKIN# item that threads a weekly Prescription pick into the
    coaching loop (#1706) — reusing the coach check-in queue, not a new mechanism.

    `follow_up` (all fields optional; a falsy/typeless value returns None — no
    follow-up is a valid pick):
      - ``type``     — ``question`` (default) or ``handoff``.
      - ``text``     — the question the coach wants Matthew to answer.
      - ``to_coach`` — for ``handoff``: the bare coach id who should raise it in
                       their next brief/check-in.

    Routing:
      - ``question`` → surfaced under the CURATING coach's queue.
      - ``handoff``  → surfaced under ``to_coach``'s queue, provenance recording
        the hand-off FROM the curating coach (mirrors how coaches already flag
        items for each other).

    Returns the item dict (caller writes it) or ``None`` when there is nothing to
    surface. Pure — `now`/`cycle` are injected so it is deterministically testable.
    Callers MUST validate ``to_coach`` against the live roster before writing.
    """
    if not follow_up:
        return None
    text = (follow_up.get("text") or "").strip()
    if not text:
        return None
    ftype = (follow_up.get("type") or FOLLOWUP_QUESTION).strip().lower()
    if ftype not in FOLLOWUP_TYPES:
        return None

    curating = normalize_coach_id(curating_coach)
    if ftype == FOLLOWUP_HANDOFF:
        target = normalize_coach_id(follow_up.get("to_coach") or "")
        if not target:
            return None
        surface_coach = target
        context_reason = f"prescription hand-off from the {curating} coach re: the week-{week} pick"
        tags = ["prescription", "horizons", "handoff", week]
    else:
        surface_coach = curating
        context_reason = f"follow-up on the {curating} coach's week-{week} prescription pick"
        tags = ["prescription", "horizons", week]

    resolve_name = coach_name_of or (lambda cid: cid)
    stamp = now or now_iso()
    item = {
        "pk": checkin_pk(surface_coach),
        # #3114: was `new_checkin_sk()` — a uuid4 suffix, so a replayed curate_horizon
        # queued the same follow-up twice. The DATE part stays wall-clock (the queue is
        # read by day); the uid is now the follow-up's own identity.
        "sk": new_checkin_sk(uid=checkin_uid(week, surface_coach, ftype, text)),
        "record_type": "coach_checkin",
        "coach_id": surface_coach,
        "coach_name": resolve_name(surface_coach),
        "question": text,
        "tags": tags,
        "status": STATUS_OPEN,
        "asked_at": stamp,
        "provenance": PROVENANCE,
        "context_reason": context_reason,
        "generated_by": "prescription_followup",
        "prescription_week": week,
        "prescription_followup_type": ftype,
        "prescription_curator": curating,
    }
    if ftype == FOLLOWUP_HANDOFF:
        item["handoff_from"] = curating
    if cycle is not None:
        item["cycle"] = int(cycle)
    return item


# ── cycle stamp (ADR-077 navigability) ───────────────────────────────────────

_cycle_cache: dict = {"value": None, "read": False}


def read_cycle(ssm_client=None):
    """Current experiment cycle (int) from SSM, fail-soft None (missing param,
    missing grant, no AWS). Only a SUCCESSFUL read is cached for the container
    lifetime — the cycle only changes on a reset, so a confirmed value never
    needs re-reading. A FAILED read is deliberately NOT latched (#1948): a
    transient SSM error (throttle, timeout) would otherwise silently drop the
    cycle stamp off every write for the rest of the warm container's life. On
    failure this returns None for THIS call only and leaves the cache unread
    so the next call retries."""
    if _cycle_cache["read"]:
        return _cycle_cache["value"]
    try:
        if ssm_client is None:
            import boto3

            ssm_client = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        raw = ssm_client.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"]
        value = int(raw)
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.warning("[coach_checkin] cycle read failed (%s) — writing without cycle stamp, will retry next call", type(e).__name__)
        return None
    _cycle_cache["value"] = value
    _cycle_cache["read"] = True
    return value


# ── #5127: which open questions still deserve the slot ───────────────────────

_DARK_MARKER = " is the longest-dark manual channel"


def _registry() -> dict:
    from ingestion.source_registry import SOURCE_REGISTRY  # lazy — bundled module

    return SOURCE_REGISTRY


def paused_sources(registry: Optional[dict] = None) -> set:
    """Registry sources off by design (`paused: True`, ADR-074 posture — food_delivery since #5006)."""
    try:
        reg = registry if registry is not None else _registry()
    except Exception as e:  # noqa: BLE001 — fail-soft: nothing paused means nothing retired for it
        logger.warning("[coach_checkin] registry read failed (%s) — no source treated as paused", type(e).__name__)
        return set()
    return {k for k, v in reg.items() if isinstance(v, dict) and v.get("paused")}


def question_source(item: dict, registry: Optional[dict] = None) -> Optional[str]:
    """The manual-capture source that drove this question, or None (rotation, explicit, follow-up).

    New rows carry `source_key` (#5127). Rows written before it say so only in prose —
    "Food delivery is the longest-dark manual channel (196d dark)" — so the label is matched
    back to the registry; an unmatched label is None, never a guess."""
    key = str((item or {}).get("source_key") or "").strip()
    if key:
        return key
    reason = str((item or {}).get("context_reason") or "")
    if _DARK_MARKER not in reason:
        return None
    label = reason.split(_DARK_MARKER, 1)[0].strip()
    try:
        reg = registry if registry is not None else _registry()
    except Exception:  # noqa: BLE001
        return None
    for key, meta in reg.items():
        if label and (label == key or (isinstance(meta, dict) and label == meta.get("label"))):
            return key
    return None


def rotate_hours_for(item: dict) -> int:
    if str((item or {}).get("generated_by") or "") == "prescription_followup":
        return PRESCRIPTION_ROTATE_HOURS
    return QUEUE_ROTATE_HOURS


def retire_verdict(item: dict, *, now: datetime, paused: set, registry: Optional[dict] = None) -> Optional[tuple]:
    """(code, reason) when an OPEN question should leave the queue, else None. Pure.

    A paused source first (the #5006 class: the question has no live signal behind it), then
    age past the rotation window (the next coach gets the turn)."""
    if (item or {}).get("status") != STATUS_OPEN:
        return None
    src = question_source(item, registry)
    if src and src in paused:
        return (
            RETIRED_SOURCE_PAUSED,
            f"its driving source {src} is paused by design (#5006, owner ruling 2026-10-23) — a question about a channel "
            "that is off on purpose has nothing live behind it",
        )
    asked = parse_iso(item.get("asked_at"))
    limit = rotate_hours_for(item)
    if asked is not None and now - asked >= timedelta(hours=limit):
        hours = int((now - asked).total_seconds() // 3600)
        return (
            RETIRED_ROTATED,
            f"open {hours}h unanswered (rotation window {limit}h) — the next coach asks instead; not a skip, zero penalty",
        )
    return None


def servable_open(items: list, *, now: Optional[datetime] = None, paused: Optional[set] = None, registry: Optional[dict] = None) -> list:
    """The open questions that still deserve a slot (oldest first) — read-only, for the session
    opener; the queue tool retires the rest."""
    now = now or utcnow()
    paused = paused_sources(registry) if paused is None else paused
    return [it for it in open_checkins(items) if retire_verdict(it, now=now, paused=paused, registry=registry) is None]


# ── reads ────────────────────────────────────────────────────────────────────


def recent_checkins(table, coach_ids, days: int = 45, limit_per_coach: int = 25) -> list:
    """All CHECKIN# items across the given coaches in the trailing window,
    newest first. Fail-soft per coach (one bad partition never hides the rest)."""
    from boto3.dynamodb.conditions import Key

    start = (pacific_now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    seen = set()
    items = []
    for cid in coach_ids:
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(checkin_pk(cid))
                & Key("sk").between(f"{CHECKIN_SK_PREFIX}{start}", f"{CHECKIN_SK_PREFIX}~"),
                ScanIndexForward=False,
                Limit=limit_per_coach,
            )
            for it in resp.get("Items", []):
                key = (it.get("pk"), it.get("sk"))
                if key in seen:
                    continue
                seen.add(key)
                items.append(it)
        except Exception as e:  # noqa: BLE001
            logger.warning("[coach_checkin] query failed for %s: %s", cid, e)
    items.sort(key=lambda it: it.get("asked_at") or it.get("sk", ""), reverse=True)
    return items


def open_checkins(items: list) -> list:
    """The still-open questions (oldest first — answer the queue FIFO)."""
    out = [it for it in items if it.get("status") == STATUS_OPEN]
    out.sort(key=lambda it: it.get("asked_at") or it.get("sk", ""))
    return out


# ── coach selection ──────────────────────────────────────────────────────────


def pick_asking_coach_detail(coach_ids, manual_signal, recent_items) -> dict:
    """{coach, reason, source}. Prefer the coach whose domain currently carries the
    most informative signal — the manual channel that is the most OVERDUE
    relative to its own staleness threshold (a long-dark channel is exactly
    where a qualitative answer beats absent quantitative data). Deterministic
    fallback: least-recently-asked rotation in canonical coach order.

    #5127: the coach who asked LAST never wins the dark-channel preference again
    straight away — one permanently dark channel used to hand the same coach every
    turn (food delivery gave nutrition every ask since July). It rotates instead.

    manual_signal: [{source, label, days_since, stale_days, coach}] — days_since
    None means "never seen", treated as maximally informative for its coach.
    """
    last_asked = {cid: "" for cid in coach_ids}
    for it in recent_items or []:
        cid = normalize_coach_id(it.get("coach_id") or "")
        if cid in last_asked:
            last_asked[cid] = max(last_asked[cid], it.get("asked_at") or "")
    newest = max(last_asked.values(), default="")
    last_coach = next((c for c in coach_ids if newest and last_asked[c] == newest), None) if len(coach_ids) > 1 else None

    best = None  # (ratio, source-entry)
    for entry in manual_signal or []:
        coach = normalize_coach_id(entry.get("coach") or "")
        if coach not in coach_ids or coach == last_coach:
            continue
        stale = entry.get("stale_days") or 0
        if stale <= 0:
            continue
        days = entry.get("days_since")
        ratio = 10.0 if days is None else days / stale
        if ratio >= 1.0 and (best is None or ratio > best[0]):
            best = (ratio, entry)
    if best:
        entry = best[1]
        days = entry.get("days_since")
        dark = "no data yet" if days is None else f"{days}d dark"
        return {
            "coach": normalize_coach_id(entry["coach"]),
            "reason": f"{entry.get('label') or entry.get('source')}{_DARK_MARKER} ({dark})",
            "source": entry.get("source"),
        }

    # Rotation fallback: the coach whose most recent check-in is oldest (never
    # asked sorts first); ties resolve by canonical order.
    coach = min(coach_ids, key=lambda c: (last_asked[c], coach_ids.index(c)))
    return {"coach": coach, "reason": "rotation — least-recently-asked coach", "source": None}


def pick_asking_coach(coach_ids, manual_signal, recent_items) -> tuple:
    """(coach_id, reason) — the tuple view of `pick_asking_coach_detail`."""
    d = pick_asking_coach_detail(coach_ids, manual_signal, recent_items)
    return d["coach"], d["reason"]


# ── question generation (Bedrock, ADR-062 chokepoint) ───────────────────────


def build_generation_prompt(coach_id, coach_name, coach_bio, snapshot, n) -> dict:
    """The Anthropic Messages body for generating n check-in questions.
    Encodes the psychology-panel rules; the snapshot grounds the questions in
    what the platform can currently see (and what it can't)."""
    presence = (snapshot or {}).get("presence") or {}
    presence_dark = presence.get("presence_class") in ("light", "quiet", "dark")

    system = (
        f"You are {coach_name}, one of the AI coaches on Matthew's personal health platform. "
        f"{coach_bio or ''}\n\n"
        "You are opening a short, OPTIONAL check-in conversation with Matthew inside Claude chat. "
        "Your job is to ask a small number of qualitative questions whose answers become context "
        "the platform's sensors cannot capture — the why behind the numbers, or the story where "
        "numbers are absent.\n\n"
        "NON-NEGOTIABLE RULES (from the platform's psychology panel):\n"
        "1. Questions must be OPEN and AUTONOMY-SUPPORTIVE — invite a story, never audit compliance. "
        "GOOD: 'what got in the way this week?', 'how did that actually feel?'. "
        "FORBIDDEN: yes/no compliance checks like 'did you take your supplements?', 'did you stick to the plan?'.\n"
        "2. Skipping any question is always valid with ZERO penalty — never phrase a question so that "
        "declining it would feel like failing.\n"
        "3. If Matthew's presence is quiet/dark (he has stopped logging), ask about BARRIERS and CONTEXT "
        "('what's been going on?', 'what would make logging feel worth it again?') — never guilt, never streak-shaming.\n"
        "4. Stay inside your own coaching domain, grounded in the live context snapshot you are given. "
        "Never invent data that isn't in the snapshot (honest-numbers rule, ADR-104).\n"
        "5. Each question is one or two sentences, conversational, in your own voice.\n\n"
        'Respond with ONLY valid JSON, no markdown fences, in this exact shape: {"questions": '
        '[{"question": "...", "tags": ["..."]}]} — tags are 1-3 lowercase topic words.'
    )
    user = (
        f"Live context snapshot (what the platform can currently see):\n{json.dumps(snapshot or {}, default=str, indent=1)}\n\n"
        + ("NOTE: presence is currently quiet/dark — rule 3 applies to EVERY question.\n\n" if presence_dark else "")
        + f"Write exactly {n} check-in question(s) for Matthew."
    )
    return {
        "model": MODEL,
        "max_tokens": 700,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }


# The generation prompt's shape, constrained at the model (#4276) via ai.structured_json.call_json.
QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["question", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def shape_questions(parsed, max_n: int = MAX_OPEN_QUESTIONS) -> list:
    """[{question, tags}] from a parsed reply; [] for anything that is not a JSON object."""
    if not isinstance(parsed, dict):
        return []
    out = []
    for q in parsed.get("questions") or []:
        if not isinstance(q, dict):
            continue
        question = str(q.get("question") or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            continue
        tags = [str(t).strip().lower() for t in (q.get("tags") or []) if str(t).strip()][:3]
        out.append({"question": question, "tags": tags})
        if len(out) >= max_n:
            break
    return out


def _bedrock_send(body: dict) -> dict:
    from common.retry_utils import call_anthropic_raw  # lazy — bundled module, runtime only

    return call_anthropic_raw(body, timeout=30)


def generate_questions(coach_id, coach_name, coach_bio, snapshot, n, caller=None) -> list:
    """Generate n questions via the Bedrock chokepoint. Fail-soft: [] on any
    error (budget tier 3, throttle, malformed JSON) — the caller degrades to
    the deterministic FALLBACK_QUESTIONS bank. `caller` injects a fake in tests."""
    n = max(1, min(int(n), MAX_OPEN_QUESTIONS))
    body = build_generation_prompt(coach_id, coach_name, coach_bio, snapshot, n)
    try:
        from ai.structured_json import call_json  # #4276: the one door for JSON-shaped model calls

        parsed = call_json(caller or _bedrock_send, body, schema=QUESTIONS_SCHEMA, label="coach_checkin")
        return shape_questions(parsed, max_n=n)
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.warning("[coach_checkin] question generation failed (%s) — falling back", type(e).__name__)
        return []


# ── consumption seam (NOT yet wired into any prompt — see #915 follow-ups) ──


def recent_checkins_block(limit_days: int = 14, max_items: int = 6, table=None, coach_ids=None) -> str:
    """A capped prompt-context block of recent ANSWERED check-ins — the
    qualitative layer a narrative prompt can cite next to the quantitative
    data. Skipped check-ins render as 'declined to answer — respect that' so a
    consumer model treats the decline as a boundary, never a gap to probe.

    Pure formatting over the store; deliberately NOT wired into
    ai_expert_analyzer / daily_brief / chronicle in #915 (those files have a
    concurrent owner) — the injection points are listed in the PR body.
    Returns "" when there is nothing to show (or on any read failure).
    """
    try:
        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
                os.environ.get("TABLE_NAME", "life-platform")
            )
        if coach_ids is None:
            from coach.persona_registry import OPERATIONAL_SHORT_IDS

            coach_ids = list(OPERATIONAL_SHORT_IDS)
        items = recent_checkins(table, coach_ids, days=max(1, int(limit_days)))
    except Exception as e:  # noqa: BLE001 — a context block must never break a prompt
        logger.warning("[coach_checkin] recent_checkins_block failed: %s", e)
        return ""

    lines = []
    for it in items:
        status = it.get("status")
        if status not in (STATUS_ANSWERED, STATUS_SKIPPED):
            continue  # open questions are not context yet
        date = (it.get("answered_at") or it.get("asked_at") or "")[:10]
        who = it.get("coach_name") or normalize_coach_id(it.get("coach_id") or "coach")
        question = str(it.get("question") or "").strip()
        if status == STATUS_SKIPPED:
            lines.append(f'- [{date} · {who}] Q: "{question}" → (declined to answer — respect that)')
        else:
            answer = str(it.get("answer") or "").strip()
            if not answer:
                continue
            lines.append(f'- [{date} · {who}] Q: "{question}" → A (verbatim): "{answer}"')
        if len(lines) >= max(1, int(max_items)):
            break
    if not lines:
        return ""
    header = (
        f"RECENT COACH CHECK-IN ANSWERS (last {limit_days}d — Matthew's own words, captured via MCP; "
        "qualitative context that pairs with, or explains the absence of, the quantitative data):"
    )
    return header + "\n" + "\n".join(lines)
