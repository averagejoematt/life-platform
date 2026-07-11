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
  * skip is always a valid answer with zero penalty;
  * when presence is dark, questions are about barriers/context — not guilt.

Phase taxonomy (ADR-077): these records SHOULD be cross_phase — qualitative
history is exactly what ought to survive an experiment reset. The one-line
registry addition in lambdas/phase_taxonomy.py is a deliberate follow-up
(another owner); until it lands, CHECKIN# rows inherit the COACH#* default
(experiment_scoped) — see the PR body for #915.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CHECKIN_SK_PREFIX = "CHECKIN#"
PROVENANCE = "mcp"
STATUS_OPEN = "open"
STATUS_ANSWERED = "answered"
STATUS_SKIPPED = "skipped"

MAX_OPEN_QUESTIONS = 3
MAX_QUESTION_CHARS = 300
MAX_ANSWER_CHARS = 4000

# Structured task → Haiku (model tiering, ADR-049); env-overridable.
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

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
    d = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{CHECKIN_SK_PREFIX}{d}#{uid or uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── cycle stamp (ADR-077 navigability) ───────────────────────────────────────

_cycle_cache: dict = {"value": None, "read": False}


def read_cycle(ssm_client=None):
    """Current experiment cycle (int) from SSM, fail-soft None (missing param,
    missing grant, no AWS). Cached for the container lifetime — the cycle only
    changes on a reset."""
    if _cycle_cache["read"]:
        return _cycle_cache["value"]
    value = None
    try:
        if ssm_client is None:
            import boto3

            ssm_client = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        raw = ssm_client.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"]
        value = int(raw)
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.info("[coach_checkin] cycle read failed (%s) — writing without cycle stamp", type(e).__name__)
    _cycle_cache["value"] = value
    _cycle_cache["read"] = True
    return value


# ── reads ────────────────────────────────────────────────────────────────────


def recent_checkins(table, coach_ids, days: int = 45, limit_per_coach: int = 25) -> list:
    """All CHECKIN# items across the given coaches in the trailing window,
    newest first. Fail-soft per coach (one bad partition never hides the rest)."""
    from boto3.dynamodb.conditions import Key

    start = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
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


def pick_asking_coach(coach_ids, manual_signal, recent_items) -> tuple:
    """(coach_id, reason). Prefer the coach whose domain currently carries the
    most informative signal — the manual channel that is the most OVERDUE
    relative to its own staleness threshold (a long-dark channel is exactly
    where a qualitative answer beats absent quantitative data). Deterministic
    fallback: least-recently-asked rotation in canonical coach order.

    manual_signal: [{source, label, days_since, stale_days, coach}] — days_since
    None means "never seen", treated as maximally informative for its coach.
    """
    best = None  # (ratio, source-entry)
    for entry in manual_signal or []:
        coach = normalize_coach_id(entry.get("coach") or "")
        if coach not in coach_ids:
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
        return (
            normalize_coach_id(entry["coach"]),
            f"{entry.get('label') or entry.get('source')} is the longest-dark manual channel ({dark})",
        )

    # Rotation fallback: the coach whose most recent check-in is oldest (never
    # asked sorts first); ties resolve by canonical order.
    last_asked = {cid: "" for cid in coach_ids}
    for it in recent_items or []:
        cid = normalize_coach_id(it.get("coach_id") or "")
        if cid in last_asked:
            last_asked[cid] = max(last_asked[cid], it.get("asked_at") or "")
    coach = min(coach_ids, key=lambda c: (last_asked[c], coach_ids.index(c)))
    return coach, "rotation — least-recently-asked coach"


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


def parse_questions(text: str, max_n: int = MAX_OPEN_QUESTIONS) -> list:
    """[{question, tags}] from the model's JSON (fenced or bare); [] if unparseable."""
    if not text:
        return []
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError):
        return []
    out = []
    for q in (parsed or {}).get("questions") or []:
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


def generate_questions(coach_id, coach_name, coach_bio, snapshot, n, caller=None) -> list:
    """Generate n questions via the Bedrock chokepoint. Fail-soft: [] on any
    error (budget tier 3, throttle, malformed JSON) — the caller degrades to
    the deterministic FALLBACK_QUESTIONS bank. `caller` injects a fake in tests."""
    n = max(1, min(int(n), MAX_OPEN_QUESTIONS))
    body = build_generation_prompt(coach_id, coach_name, coach_bio, snapshot, n)
    try:
        if caller is None:
            from retry_utils import call_anthropic_raw  # lazy — bundled module, runtime only

            result = call_anthropic_raw(body, timeout=30)
        else:
            result = caller(body)
        text = "".join(b.get("text", "") for b in (result or {}).get("content", []) if b.get("type") == "text")
        return parse_questions(text, max_n=n)
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
            from persona_registry import OPERATIONAL_SHORT_IDS

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
