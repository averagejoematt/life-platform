"""telegram_worker_lambda.py — the async half of the coach chat (#2364, epic #2363).

The webhook Lambda answers Telegram inside its retry window and async-invokes this
worker with a small work order ({coach_id, chat_id, text, message_id}). Everything
slow happens here: the typing indicator, the memory reads, the Bedrock call, the
grounding gate, the reply, the storage.

This module is deliberately an ASSEMBLY of parts that are each already built and
tested elsewhere — the design rule of the whole epic:

  * WHO the coach is        → persona_core.persona_block (the voice specs)
  * WHAT they remember      → the COACH# partition (CHAT# thread, RELATIONSHIP#state)
  * WHAT is true today      → canonical_facts via the computed_metrics record — the
                              SAME record every coach card cites, so the phone and
                              the site cannot tell two truths
  * the turn itself         → coach_chat.run_turn (regenerate-or-hold, budget gates)
  * the grounding closure   → coach_chat_grounding.build_grounder (all five classes)
  * the model               → bedrock_client.invoke (ADR-062's single chokepoint)

The only genuinely new behaviour here is Telegram's sendMessage/sendChatAction —
urllib, per the no-HTTP-libraries rule.

OUTBOUND (Act 1b). Two paths let a coach text FIRST — a referral handoff after a
reply, and Eli's weekday morning check-in on a scheduled event. Both assemble
exactly the same way as an inbound turn (same persona, same memory, same facts,
same full grounding gate); what differs is the gate in front of them, which lives
in ``coach.coach_outbound``: a shared daily ledger, quiet hours, and a hard
requirement that the target coach's bot ALREADY EXISTS with this chat on its
roster. That last one is why the whole feature is dark by default — a coach with
no BotFather registration cannot be handed anything, and no code flag has to
remember that.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import boto3

try:
    from common.platform_logger import get_logger

    logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

from coach import coach_chat, coach_outbound, telegram_gateway
from coach.coach_chat_grounding import build_facts_block, build_grounder
from coach.persona_registry import LEAD_PERSONA_ID, display_name, persona_for_telegram_route

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
STORE_PATH = os.environ.get("TELEGRAM_SECRET_ID", "life-platform/telegram")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Narrative register on a personal chat surface — Sonnet, same tier as the coach
# cards (structured tasks take Haiku; a coach texting in their own voice is not a
# structured task).
MODEL = os.environ.get("AI_MODEL", "us.anthropic.claude-sonnet-4-6")

_dynamodb = None
_secrets = None
_s3 = None
_cw = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(TABLE_NAME)


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=REGION)
    return _s3


def _emit_metric(name: str, coach_id: str) -> None:
    """Fail-loud partner of the persona fix: a coach chatting without its identity
    is an incident, not a WARN. Emission itself is fail-soft — a metrics outage
    must not block the reply."""
    global _cw
    try:
        if _cw is None:
            _cw = boto3.client("cloudwatch", region_name=REGION)
        _cw.put_metric_data(
            Namespace="LifePlatform/Telegram",
            MetricData=[
                {
                    "MetricName": name,
                    "Dimensions": [{"Name": "Coach", "Value": coach_id}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        logger.warning("[telegram] metric %s emit failed: %s", name, e)


def _secret_entry(coach_key: str) -> dict:
    """One route's entry in the telegram store ({bot_token, chat_ids}), or {}.

    A route with no entry is a bot that does not exist yet — the state every
    chat-tier coach is in until the owner's BotFather run. Fail-soft {} so that
    reads as "dark", never as a crash.
    """
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    from common.secret_cache import get_secret_json

    try:
        return (get_secret_json(STORE_PATH, _secrets) or {}).get(coach_key) or {}
    except Exception as e:
        logger.warning("[telegram] secret store unreadable for %s: %s", coach_key, e)
        return {}


def _bot_token(coach_key: str) -> Optional[str]:
    return _secret_entry(coach_key).get("bot_token")


def _bot_chat_ids(coach_key: str) -> list:
    """The chat ids this bot is allowed to talk to (the setup script discovers
    them from Matthew's own first message). Empty = registered-but-unmessaged, or
    not registered at all; either way nothing outbound may be sent to it."""
    return list(_secret_entry(coach_key).get("chat_ids") or [])


def _chat_authorized(chat_id, chat_ids: list) -> bool:
    """Whether this conversation exists on that bot's roster. String-compared
    because Telegram ids arrive as ints from the API and as strings from a
    hand-edited secret, and a type mismatch here would silently dark the whole
    handoff path."""
    return str(chat_id) in {str(c) for c in chat_ids or []}


def _tg(token: str, method: str, payload: dict) -> None:
    """One Telegram Bot API call. Fire-and-log — a failed typing indicator or even a
    failed send must never crash the worker into Lambda retries (which would re-run
    inference and double-charge the budget for one message)."""
    try:
        req = urllib.request.Request(
            TELEGRAM_API.format(token=token, method=method),
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
    except Exception as e:
        logger.warning("[telegram] %s failed: %s", method, e)


# ── Memory + facts assembly ───────────────────────────────────────────────────


def _chat_rows(coach_id: str, limit: int = 40) -> list:
    """The coach's recent CHAT# turn rows, oldest-first, WHOLE items.

    Whole items rather than {role, text} because the outbound side needs the
    ``provenance`` attribute too: "did my last two check-ins go unanswered" is a
    question about which rows were unsolicited, and a role/text projection cannot
    answer it. Role filter, not just a text filter: CHAT#summary# rows live inside
    the CHAT# prefix by design (one cross-phase family) and must never be read
    back as turns.
    """
    try:
        resp = _table().query(
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


def _thread_today(coach_id: str, limit: int = 40) -> list:
    """Today's + yesterday's stored turns, oldest-first — the conversational memory."""
    return [{"role": i.get("role"), "text": i.get("text")} for i in _chat_rows(coach_id, limit)]


def _turns_today(thread: list) -> int:
    return len([t for t in thread if t.get("role") == coach_chat.ROLE_MATTHEW])


def _colleagues_block(self_persona_id: str, allow_referral: bool = False) -> str:
    """The staff roster, from THIS coach's seat — real names + pronouns, so a
    cross-reference is 'Dr. Nathan Reeves (he)' and never 'the mind coach (her)'.
    Consulting specialists are included: citable-by-name is their whole tier.
    Fail-soft "" — a roster miss never blocks the reply.

    ``allow_referral`` is the prompt seam for the handoff marker (Act 1b): it
    appends the handoff id to each line and the permission sentence to the block.
    OFF by default, and deliberately off on an outbound turn — a referral that can
    itself refer is a chain, and a chain is how two coaches become five texts.
    """
    try:
        from coach.persona_registry import personas

        lines = []
        for pid, p in personas(s3_client=_s3_client(), bucket=S3_BUCKET).items():
            if pid == self_persona_id or not (p.get("operational") or p.get("chat") or p.get("consulting")):
                continue
            pr = f" ({p['pronouns']})" if p.get("pronouns") else ""
            role = p.get("title") or p.get("board_role") or ""
            handoff = f" [handoff id: {pid}]" if allow_referral else ""
            lines.append(f"- {p['name']}{pr} — {role}{handoff}")
        if not lines:
            return ""
        block = "YOUR COLLEAGUES (refer to them by name, with these pronouns):\n" + "\n".join(lines)
        return f"{block}\n\n{coach_outbound.REFERRAL_RULE}" if allow_referral else block
    except Exception as e:
        logger.warning("[telegram] colleagues block unavailable: %s", e)
        return ""


def _last_reply_had_emoji(thread: list) -> bool:
    """Whether the coach's most recent stored reply carried an emoji — feeds the
    never-twice-in-a-row half of the deterministic emoji ceiling."""
    for t in reversed(thread or []):
        if t.get("role") == coach_chat.ROLE_COACH:
            return coach_chat.has_emoji(t.get("text") or "")
    return False


def _memory_block(coach_id: str) -> str:
    """What this coach knows about Matthew — relationship state + recent memory rows.

    Reads the SAME partition the dossier renders, so the phone conversation and the
    public 'what this coach knows' page cannot diverge. Fail-soft: a coach with an
    unreadable memory chats from persona + facts alone, honestly."""
    pk = coach_chat.chat_pk(coach_id)
    lines = []
    try:
        # #946/#1969: a restart tombstones singletons IN PLACE — an unguarded get_item
        # would feed the wiped cycle's relationship arc into a fresh-cycle chat.
        from experiment.phase_filter import singleton_visible

        rel = _table().get_item(Key={"pk": pk, "sk": "RELATIONSHIP#state"}).get("Item") or {}
        if not singleton_visible(rel):
            rel = {}
        phase = rel.get("phase")
        if phase:
            lines.append(f"Your working relationship with Matthew is in the '{phase}' phase.")
    except Exception as e:
        logger.warning("[telegram] relationship read failed: %s", e)
    for prefix, label, cap in (("COMMITMENT#", "Commitments you hold him to", 3), ("LEARNING#", "Things you have learned about him", 3)):
        try:
            resp = _table().query(
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

        summaries = read_recent_summaries(_table(), pk)
        if summaries:
            block = f"{block}\n\n{summaries}" if block else summaries
    except Exception as e:
        logger.warning("[telegram] chat summaries unavailable: %s", e)
    return block


def _facts() -> dict:
    """The one authoritative daily fact set — the same computed_metrics record every
    coach card cites, through the SAME extraction (`build_canonical_facts`, which
    carries the #2113 semantics: a pre-genesis record is withheld). The read is the
    analyzer's own idiom — newest computed_metrics row, direct query. Fail-soft: an
    empty dict makes the facts block say 'no numbers to cite' out loud."""
    try:
        from decimal import Decimal

        from experiment import phase_taxonomy
        from experiment.canonical_facts import build_canonical_facts

        pk = "USER#matthew#SOURCE#computed_metrics"
        # #2113: computed_metrics is experiment-scoped — the read FLOORS at the cycle
        # genesis, exactly as the analyzer's _latest_item does, or a pre-genesis record
        # speaks for this cycle ("your recovery came in at 59%" against a cockpit
        # serving 44 — the incident the rider exists for).
        kwargs: dict = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": pk},
            "ScanIndexForward": False,
            "Limit": 1,
        }
        floor = phase_taxonomy.cycle_read_floor(pk)
        if floor:
            kwargs["KeyConditionExpression"] += " AND sk BETWEEN :lo AND :hi"
            kwargs["ExpressionAttributeValues"][":lo"] = f"DATE#{floor}"
            kwargs["ExpressionAttributeValues"][":hi"] = "DATE#9999-12-31"
        items = _table().query(**kwargs).get("Items") or []
        if not items:
            return {}
        record = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in items[0].items()}
        return build_canonical_facts(record)
    except Exception as e:
        logger.warning("[telegram] facts unavailable: %s", e)
        return {}


def _current_tier() -> Optional[int]:
    try:
        from ai.budget_guard import current_tier

        return current_tier()
    except Exception as e:
        logger.warning("[telegram] tier read failed (proceeding — the hard backstop is bedrock_client): %s", e)
        return None


# ── The handler ───────────────────────────────────────────────────────────────


def _partition_id(route: str) -> str:
    """Persona-derived partition key input for a Telegram route — the same
    resolution the handler performs later, callable before it (dedupe runs
    first). Falls back to the route itself (old behaviour) offline."""
    try:
        pid, _ = persona_for_telegram_route(route)
        return pid or route
    except Exception:
        return route


def _seen_update(coach_id: str, update_id) -> bool:
    """True when this Telegram update was already processed (redelivery).

    Conditional put on a TTL'd DEDUPE row in the coach's own partition — the
    write the worker is already scoped to (LeadingKeys COACH#*). Fail-OPEN on
    any storage error: a dropped real message looks exactly like a broken bot,
    a rare double-answer merely looks eager.
    """
    if update_id is None:
        return False
    import time as _time

    try:
        _table().put_item(
            Item={
                "pk": coach_chat.chat_pk(coach_id),
                "sk": f"DEDUPE#{update_id}",
                "type": "telegram_dedupe",
                "ttl": int(_time.time()) + 24 * 3600,
            },
            ConditionExpression="attribute_not_exists(sk)",
        )
        return False
    except Exception as e:
        if e.__class__.__name__ == "ConditionalCheckFailedException":
            return True
        logger.warning("[telegram] dedupe check failed (proceeding): %s", e)
        return False


def _current_moment_line() -> str:
    """WHAT TIME IT IS — the context the screenshots proved missing ("I don't
    have access to the current date or time"). Pacific, matching every other
    surface (site convention). Joins the facts block AND the grounder's allowed
    vocabulary, so citing today's date is never flagged as fabrication."""
    try:
        from common.pacific_time import pacific_now

        now = pacific_now()
        return f"CURRENT MOMENT: {now.strftime('%A')}, {now.strftime('%Y-%m-%d')}, {now.strftime('%I:%M %p').lstrip('0')} Pacific."
    except Exception as e:  # pragma: no cover — import edge; honesty over crash
        logger.warning("[telegram] current-moment line failed: %s", e)
        return ""


def _pacific_now():
    """The one clock. Injected nowhere and read here so every gate below asks the
    same module the site asks (no inline ZoneInfo — #1964)."""
    from common.pacific_time import pacific_now

    return pacific_now()


def _cycle() -> Optional[int]:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
    except Exception:
        return None


def _assemble(persona_id: str, coach_id: str, *, allow_referral: bool = False) -> dict:
    """Everything one coach needs to speak, in one place.

    Factored out of the inbound handler so the two OUTBOUND paths cannot quietly
    diverge from it. A referral or a check-in that assembled its own thinner
    prompt would be a second, less-grounded coach wearing the same name — the
    exact fork this epic's design rule exists to prevent. One assembly, three
    callers, same persona/memory/facts/grounder every time.
    """
    coach_name = display_name(persona_id, s3_client=_s3_client(), bucket=S3_BUCKET)
    if not coach_name or coach_name == persona_id:
        _emit_metric("TelegramPersonaMissing", coach_id)
        logger.error("[telegram] persona registry unreadable for %s — degraded name", persona_id)
        coach_name = f"Matthew's {coach_chat.normalize_coach_id(coach_id)} coach"

    thread = _thread_today(persona_id)
    facts = _facts()
    memory = _memory_block(persona_id)

    try:
        from coach.persona_core import load_voice_spec, persona_block, texting_block

        persona = persona_block(persona_id, s3_client=_s3_client(), bucket=S3_BUCKET)
        # The texting register joins ONLY here — the board and the observatory
        # keep the same soul without being told how to text (#2402).
        texting = texting_block(load_voice_spec(persona_id, s3_client=_s3_client(), bucket=S3_BUCKET))
        if persona and texting:
            persona = f"{persona}\n\n{texting}"
    except Exception as e:
        logger.warning("[telegram] persona load failed: %s", e)
        persona = ""
    if not persona:
        _emit_metric("TelegramVoiceSpecMissing", coach_id)
        logger.error("[telegram] voice spec unreadable for %s — replying without persona", persona_id)

    # The current moment + the coach's DOMAIN pack join the FACTS the coach may
    # cite — and the grounder's allowed vocabulary, so naming today or its own
    # domain numbers is never flagged as fabrication. The night map stays
    # canonical-facts-only (#2343): the pack widens vocabulary, never vitals.
    moment = _current_moment_line()
    # PACIFIC, not UTC (Act 1a). Three things have to name the SAME day or the
    # coach argues with its own gate: the domain pack's date windows, the
    # experiment frame's Day-N, and the grounder's deterministic Day-N
    # adjudication. Between 5pm PT and midnight the UTC date is already tomorrow,
    # which is precisely when Matthew texts. None falls both callees back to
    # their prior UTC default.
    today_pt = None
    try:
        today_pt = _pacific_now().strftime("%Y-%m-%d")
    except Exception as e:  # pragma: no cover — import edge
        logger.warning("[telegram] pacific date unavailable: %s", e)
    domain = ""
    try:
        from coach.coach_domain_facts import domain_facts_block

        domain = domain_facts_block(persona_id, _table(), today_pt)
    except Exception as e:
        logger.warning("[telegram] domain facts unavailable: %s", e)
    facts_block = build_facts_block(facts)
    if moment:
        facts_block = f"{facts_block}\n{moment}"
    if domain:
        facts_block = f"{facts_block}\n\n{domain}"

    return {
        "persona_id": persona_id,
        "coach_name": coach_name,
        "persona": persona,
        "thread": thread,
        "facts": facts,
        "facts_block": facts_block,
        "memory": memory,
        "moment": moment,
        "domain": domain,
        "today_pt": today_pt,
        "colleagues": _colleagues_block(persona_id, allow_referral=allow_referral),
    }


def _grounder_for(a: dict, *extra: str):
    """The five-class grounder, armed over everything this coach was given.

    ``generation_date_iso`` rides through so an OUTBOUND turn adjudicates Day-N
    against the same Pacific day the inbound path does — a referral generated at
    5:30pm PT must not be gated against tomorrow's UTC date.
    """
    return build_grounder(
        a["facts"],
        generation_date_iso=a["today_pt"],
        extra_sources=(
            a["memory"],
            a["moment"],
            a["domain"],
            " ".join(t.get("text") or "" for t in a["thread"]),
            *[e for e in extra if e],
        ),
    )


def _send_bubbles(token: str, chat_id, bubbles: list, *, max_bubbles: Optional[int] = None) -> list:
    """Send 1..n bubbles ~1s apart with the typing indicator between — the texture
    of a person, not a report renderer. Markers are stripped on EVERY path here,
    so machine syntax can never reach the phone. Returns what was actually sent."""
    import time as _time

    sendable = coach_outbound.strip_referral_markers(bubbles) or []
    if max_bubbles and len(sendable) > max_bubbles:
        sendable = sendable[: max_bubbles - 1] + ["\n\n".join(sendable[max_bubbles - 1 :])]
    for i, bubble in enumerate(sendable):
        if i:
            _tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
            _time.sleep(1.0)
        _tg(token, "sendMessage", {"chat_id": chat_id, "text": bubble})
    return sendable


def _store_outbound(persona_id: str, coach_name: str, frame: str, result, provenance: str, extra: Optional[dict] = None) -> None:
    """Store the coach half of an unsolicited turn — and ONLY the coach half.

    ``turn_records`` builds a Matthew row and a coach row, which is right for a
    conversation. Here there was no Matthew message: the frame is an instruction
    the platform wrote. Storing it under his name would put words in his mouth in
    the coach's own memory, so the frame is discarded and only what the coach
    actually said is kept, stamped with the provenance that says how it started.
    """
    try:
        records = coach_chat.turn_records(persona_id, coach_name, frame, result, cycle=_cycle())
        if not records:
            return
        row = dict(records[-1])
        row["provenance"] = provenance
        if extra:
            row.update(extra)
        _table().put_item(Item=row)
    except Exception as e:
        logger.warning("[telegram] outbound storage failed (message already sent): %s", e)


# ── Outbound path 1: the referral handoff ─────────────────────────────────────


def _maybe_refer(*, marker: Optional[str], referring: dict, chat_id, thread: list, inbound: str, reply_text: str) -> Optional[str]:
    """A colleague texts Matthew ONCE, because this conversation was theirs.

    Every condition below is checked in CODE, not asked of a model, and every one
    of them fails DARK. The chat-id membership test is the load-bearing one: a
    coach whose bot the owner has not created yet simply cannot be handed
    anything, so the feature ships live and stays silent until BotFather says
    otherwise. Returns the persona_id texted, or None.
    """
    from coach.persona_registry import personas, resolve

    self_id = referring["persona_id"]
    target = coach_outbound.resolve_referral_target(marker, personas(s3_client=_s3_client(), bucket=S3_BUCKET), self_id)
    if not target:
        if marker:
            logger.info("[telegram] referral marker %r from %s did not resolve — no handoff", marker, self_id)
        return None

    p = resolve(target, _s3_client(), S3_BUCKET) or {}
    route = p.get("telegram_route")
    token = _bot_token(route) if route else None
    if not token or not _chat_authorized(chat_id, _bot_chat_ids(route)):
        logger.info("[telegram] referral to %s dark — bot not registered for this chat", target)
        return None

    now = _pacific_now()
    if coach_outbound.in_quiet_hours(now):
        logger.info("[telegram] referral to %s suppressed — quiet hours (%s PT)", target, now.hour)
        return None

    tier = _current_tier()
    if tier is not None and tier >= coach_chat._PAUSE_TIER:
        logger.info("[telegram] referral to %s skipped — budget tier %s", target, tier)
        return None

    # The claim comes BEFORE inference, not before the send: a crash between
    # generating and sending must not license a second attempt later (#1382's
    # reserve-then-act idiom).
    if not coach_outbound.claim_outbound(_table(), now.strftime("%Y-%m-%d"), referral=True):
        return None

    a = _assemble(target, target)
    tail = coach_outbound.render_tail(
        list(thread) + [{"role": coach_chat.ROLE_MATTHEW, "text": inbound}, {"role": coach_chat.ROLE_COACH, "text": reply_text}],
        "Matthew",
        referring["coach_name"],
    )
    frame = coach_outbound.referral_frame(referring["coach_name"], tail)

    from ai import bedrock_client

    result = coach_chat.run_turn(
        coach_id=target,
        coach_name=a["coach_name"],
        persona_block=a["persona"],
        memory_block=a["memory"],
        facts_block=a["facts_block"],
        thread=a["thread"],
        inbound=frame,
        model=MODEL,
        caller=lambda body: bedrock_client.invoke(body),
        # The tail joins the allowed vocabulary: a coach repeating a number its
        # colleague just cited is quoting, not fabricating.
        grounder=_grounder_for(a, tail),
        tier=tier,
        turns_today=_turns_today(a["thread"]),
        last_reply_had_emoji=_last_reply_had_emoji(a["thread"]),
        colleagues_block=a["colleagues"],
    )
    if not result.grounded:
        # An unsolicited "let me check that" is a buzz that says nothing. A reply
        # earns the honest deferral because he asked; this does not.
        logger.info("[telegram] referral to %s held (%s) — not sending unsolicited", target, result.status)
        return None

    sent = _send_bubbles(token, chat_id, result.bubbles or [result.text], max_bubbles=1)
    if not sent:
        return None
    _store_outbound(target, a["coach_name"], frame, result, coach_outbound.PROVENANCE_REFERRAL, extra={"referred_by": self_id})
    logger.info("[telegram] referral %s → %s sent", self_id, target)
    return target


# ── Outbound path 2: the morning check-in ─────────────────────────────────────


def _morning_checkin() -> dict:
    """Eli opens the weekday, with the one thing that matters today.

    Dark until his bot exists — and dark again the moment two of these in a row
    go unanswered, which is the part that keeps a check-in from becoming a
    notification.
    """
    now = _pacific_now()
    if now.weekday() >= 5:
        logger.info("[telegram] morning check-in skipped — weekend (%s PT)", now.date())
        return {"ok": True, "reason": "weekend"}

    from coach.persona_registry import resolve

    persona_id = LEAD_PERSONA_ID
    route = (resolve(persona_id, _s3_client(), S3_BUCKET) or {}).get("telegram_route")
    token = _bot_token(route) if route else None
    chat_ids = _bot_chat_ids(route) if route else []
    if not token or not chat_ids:
        logger.info("[telegram] morning check-in dark — bot not registered (%s)", persona_id)
        return {"ok": True, "reason": "dark"}
    chat_id = chat_ids[0]

    if coach_outbound.in_quiet_hours(now):
        logger.info("[telegram] morning check-in suppressed — quiet hours (%s PT)", now.hour)
        return {"ok": True, "reason": "quiet hours"}

    if coach_outbound.two_consecutive_ignored(_chat_rows(persona_id), coach_outbound.PROVENANCE_CHECKIN):
        logger.info("[telegram] morning check-in skipped — last two went unanswered")
        return {"ok": True, "reason": "silence respected"}

    tier = _current_tier()
    if tier is not None and tier >= coach_chat._PAUSE_TIER:
        logger.info("[telegram] morning check-in skipped — budget tier %s", tier)
        return {"ok": True, "reason": "budget"}

    if not coach_outbound.claim_outbound(_table(), now.strftime("%Y-%m-%d")):
        return {"ok": True, "reason": "capped"}

    a = _assemble(persona_id, persona_id)
    frame = coach_outbound.checkin_frame()

    from ai import bedrock_client

    result = coach_chat.run_turn(
        coach_id=persona_id,
        coach_name=a["coach_name"],
        persona_block=a["persona"],
        memory_block=a["memory"],
        facts_block=a["facts_block"],
        thread=a["thread"],
        inbound=frame,
        model=MODEL,
        caller=lambda body: bedrock_client.invoke(body),
        grounder=_grounder_for(a),
        tier=tier,
        turns_today=_turns_today(a["thread"]),
        last_reply_had_emoji=_last_reply_had_emoji(a["thread"]),
        colleagues_block=a["colleagues"],
    )
    if not result.grounded:
        logger.info("[telegram] morning check-in held (%s) — not sending unsolicited", result.status)
        return {"ok": True, "reason": "held"}

    sent = _send_bubbles(token, chat_id, result.bubbles or [result.text], max_bubbles=2)
    if not sent:
        return {"ok": True, "reason": "empty"}
    _store_outbound(persona_id, a["coach_name"], frame, result, coach_outbound.PROVENANCE_CHECKIN)
    logger.info("[telegram] morning check-in sent (%s bubbles)", len(sent))
    return {"ok": True, "status": result.status, "bubbles": len(sent)}


def lambda_handler(event: dict, context: object) -> dict:  # noqa: ARG001 — Lambda signature
    """One work order in, one Telegram reply out (or one honest refusal).

    Two shapes arrive here: a webhook work order (coach_id/chat_id/text) and a
    scheduled outbound event ({"kind": ...}). Discriminated on the explicit
    ``kind`` rather than on which fields are missing — a malformed work order
    must stay a malformed work order, not silently become a check-in.
    """
    if (event or {}).get("kind") == "morning_checkin":
        return _morning_checkin()

    order = event or {}
    coach_id = order.get("coach_id")
    chat_id = order.get("chat_id")
    text = order.get("text") or ""
    if not coach_id or chat_id is None or not text.strip():
        logger.warning("[telegram] malformed work order: %s", {k: order.get(k) for k in ("coach_id", "chat_id")})
        return {"ok": False, "reason": "malformed order"}

    # Redelivered update (Telegram retries after outages/late webhook registration)
    # — already answered once; answering again is the double-greeting from go-live.
    if _seen_update(_partition_id(coach_id), order.get("update_id")):
        logger.info("[telegram] duplicate update %s for %s — skipping", order.get("update_id"), coach_id)
        return {"ok": True, "reason": "duplicate"}

    # A backlogged message from hours ago reads as a bot waking up, not a person
    # answering. Skip inference; the message stays visible in the Telegram chat.
    import time as _time

    if telegram_gateway.is_stale(order.get("message_date"), _time.time()):
        _emit_metric("TelegramStaleSkipped", coach_id)
        logger.info("[telegram] stale message for %s (sent %s) — skipping", coach_id, order.get("message_date"))
        return {"ok": True, "reason": "stale"}

    token = _bot_token(coach_id)
    if not token:
        logger.warning("[telegram] no bot token for %s — dropping", coach_id)
        return {"ok": False, "reason": "no token"}

    _tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})

    # Route → persona is REGISTRY data (coaching-team v2): chat-tier coaches like
    # eli_marsh broke the old f"{route}_coach" string surgery. The derivation
    # stays as the offline fallback so a registry outage degrades, never renames.
    persona_id, _route_persona = persona_for_telegram_route(coach_id, s3_client=_s3_client(), bucket=S3_BUCKET)
    if not persona_id:
        persona_id = f"{coach_chat.normalize_coach_id(coach_id)}_coach"
    # S3 first (fresh config without a redeploy), bundled config/ as the offline
    # fallback — the pair of paths that was MISSING when every conversation ran
    # nameless ("I'm mind_coach") and persona-free. Both failing is an incident:
    # metric + alarm, and an honest role-name instead of a leaked internal id.
    a = _assemble(persona_id, coach_id, allow_referral=True)
    coach_name = a["coach_name"]
    thread = a["thread"]

    from ai import bedrock_client

    result = coach_chat.run_turn(
        coach_id=coach_id,
        coach_name=coach_name,
        persona_block=a["persona"],
        memory_block=a["memory"],
        facts_block=a["facts_block"],
        thread=thread,
        inbound=text,
        model=MODEL,
        caller=lambda body: bedrock_client.invoke(body),
        # All five gate classes armed; the memory block and thread text widen the
        # NUMBER vocabulary (quoting memory is not fabrication) while the night map
        # stays facts-only — #2343's class is checked even on remembered figures.
        grounder=_grounder_for(a),
        tier=_current_tier(),
        turns_today=_turns_today(thread),
        last_reply_had_emoji=_last_reply_had_emoji(thread),
        colleagues_block=a["colleagues"],
    )

    # A burst goes out as separate bubbles ~1s apart with the typing indicator
    # between — the texture of a person, not a report renderer. Bounded: at most
    # MAX_BUBBLES-1 pauses on a Lambda already sized for a Bedrock round-trip.
    # Any handoff marker is read off the gated text and STRIPPED before the first
    # bubble leaves — Matthew never sees machine syntax, whether or not the
    # deterministic gate below lets the handoff through.
    marker = coach_outbound.parse_referral(result.text)
    sent = _send_bubbles(token, chat_id, result.bubbles or [result.text])
    if not sent and result.text:
        # Degenerate: the model replied with NOTHING but a handoff marker, so
        # stripping it left no message. Rare, but it must not be invisible — and
        # the honest response is not to invent a sentence to fill the silence.
        # The raw output is stored verbatim (below) so the record shows exactly
        # what happened, and the handoff itself still runs.
        _emit_metric("TelegramEmptyAfterMarkerStrip", coach_id)
        logger.error("[telegram] %s replied with a marker and nothing else — nothing sent", persona_id)

    # The exchange joins the coach's real memory — including a held turn, with its
    # findings, so a later reader sees the coach declined and why, not a gap. What
    # is stored is what was SENT: the marker was never part of what he read.
    reply_text = "\n\n".join(sent) if sent else result.text
    cycle = _cycle()
    try:
        table = _table()
        for item in coach_chat.turn_records(persona_id, coach_name, text, result, cycle=cycle):
            if item.get("role") == coach_chat.ROLE_COACH:
                item["text"] = reply_text
            table.put_item(Item=item)
    except Exception as e:
        logger.warning("[telegram] turn storage failed (reply already sent): %s", e)

    # Long-memory upkeep AFTER the reply is out: summarize the most recent
    # un-summarized past chat day (lazily scheduled — no cron, no cdk). Shares
    # the chat's own budget posture; a tier that pauses chat never summarizes.
    try:
        tier = _current_tier()
        if tier is None or tier < 2:
            from coach.coach_chat_summary import ensure_daily_summary

            ensure_daily_summary(
                _table(), coach_chat.chat_pk(persona_id), coach_name, lambda body: bedrock_client.invoke(body), cycle=cycle
            )
    except Exception as e:
        logger.warning("[telegram] chat summary upkeep failed (reply already sent): %s", e)

    # The handoff, LAST and fully insulated: Matthew's reply is already on his
    # phone, so nothing in the outbound path — a registry miss, a dark bot, a
    # ledger error — can cost him the answer he actually asked for.
    referred = None
    try:
        referred = _maybe_refer(
            marker=marker,
            referring={"persona_id": persona_id, "coach_name": coach_name},
            chat_id=chat_id,
            thread=thread,
            inbound=text,
            reply_text=reply_text,
        )
    except Exception as e:
        logger.warning("[telegram] referral path failed (reply already sent): %s", e)

    logger.info("[telegram] %s turn %s (attempts=%d findings=%d)", coach_id, result.status, result.attempts, len(result.findings))
    out = {"ok": True, "status": result.status}
    if referred:
        out["referred_to"] = referred
    return out


def _now_iso() -> str:  # pragma: no cover — debugging aid
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Alias kept for callers/tests that used the short name pre-I3 rename.
handler = lambda_handler
