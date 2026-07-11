"""
podcast_script_v2.py — the two-pass podcast script engine + show memory (#547).

The single-call script was the tell of fake dialogue: one model wrote both
speakers. v2 writes Elena first (her voice, her memory, the show's callbacks),
then the guest coach separately IN THEIR OWN VOICE SPEC reacting to Elena's
ACTUAL lines. Disagreement segments cite the real record — the #540 inter-coach
threads and the ensemble's live unresolved topics — never invented banter. The
show-memory ledger (SHOW#memory in the panelcast partition) is deterministic
content from real records: past episodes' titles/pull-quotes/bets + guest
history; the prompt lands at least one callback when material exists.

Split out of coach_panel_podcast_lambda (the *_lambda size gate); dependencies
arrive via the `deps` dict so this module is pure enough to test without AWS:
  deps = {table, s3, bucket, user_id, writer_model, invoke,
          extract_json, elena_host_state, episode_angle, logger}

The output contract of build_weekly_script_v2 is identical to the v1 builder
({turns, open_bet, last_bet_result, pull_quote, episode_title}), so every
downstream gate — per-line ER-03, the safety gate, QA + revisions, HOLD,
human-in-loop — is untouched. Any failure returns {} and the caller falls back
to v1: the show never dies to an upgrade.
"""

import json
from datetime import datetime, timezone

SHOW_MEMORY_SK = "SHOW#memory"
MAX_CALLBACKS = 10
MAX_GUEST_HISTORY = 12
TURN_CAP = 22


def load_show_memory(table, user_id, logger) -> dict:
    """The episode-memory ledger — callbacks + guest history. Absence = empty
    memory (seeded on the first v2 publish), never an error."""
    memory = {"callbacks": [], "guest_history": []}
    try:
        it = table.get_item(Key={"pk": f"USER#{user_id}#SOURCE#panelcast", "sk": SHOW_MEMORY_SK}).get("Item")
        if it:
            memory["callbacks"] = [dict(c) for c in (it.get("callbacks") or [])][-MAX_CALLBACKS:]
            memory["guest_history"] = [dict(g) for g in (it.get("guest_history") or [])][-MAX_GUEST_HISTORY:]
    except Exception as e:
        logger.warning("[panel] show memory read failed — %s", e)
    return memory


def write_show_memory(table, user_id, logger, week, title, pull_quote, guest_id, guest_name, open_bet) -> None:
    """Append this episode to the ledger (capped, idempotent per week, fail-soft)."""
    try:
        memory = load_show_memory(table, user_id, logger)
        cbs = [c for c in memory["callbacks"] if c.get("week") != week]
        cbs.append({"week": week, "title": title or "", "pull_quote": pull_quote or "", "open_bet": open_bet or ""})
        gh = [g for g in memory["guest_history"] if g.get("week") != week]
        gh.append({"week": week, "coach_id": guest_id, "name": guest_name or guest_id})
        table.put_item(
            Item={
                "pk": f"USER#{user_id}#SOURCE#panelcast",
                "sk": SHOW_MEMORY_SK,
                "record_type": "show_memory",
                "callbacks": cbs[-MAX_CALLBACKS:],
                "guest_history": gh[-MAX_GUEST_HISTORY:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.warning("[panel] show memory write failed — %s", e)


def dispute_material(table, logger) -> str:
    """Genuine disagreement on the record: the latest #540 inter-coach thread
    (an ACTUAL exchange) + the ensemble's live unresolved topics. Empty string
    when nothing real exists — the show then has no Split fuel, it never
    invents banter."""
    from boto3.dynamodb.conditions import Key

    lines = []
    try:
        th = table.query(KeyConditionExpression=Key("pk").eq("ENSEMBLE#dispute"), ScanIndexForward=False, Limit=1).get("Items", [])
        if th:
            t = th[0]
            lines.append(f"AIRED DISPUTE ({t.get('week')}): {t.get('topic')}")
            for turn in list(t.get("turns") or [])[:3]:
                lines.append(f"  {turn.get('name', turn.get('speaker'))}: {str(turn.get('line', ''))[:220]}")
    except Exception as e:
        logger.warning("[panel] dispute thread read failed — %s", e)
    try:
        topics = table.query(
            KeyConditionExpression=Key("pk").eq("ENSEMBLE#disagreements") & Key("sk").begins_with("ACTIVE#"), Limit=10
        ).get("Items", [])
        for t in [t for t in topics if t.get("status") in (None, "unresolved")][:2]:
            lines.append(f"OPEN ARGUMENT (cycle_count {int(t.get('cycle_count') or 1)}): {t.get('topic')}")
    except Exception as e:
        logger.warning("[panel] disagreement topics read failed — %s", e)
    return "\n".join(lines)


def memory_block(memory: dict) -> str:
    if not memory.get("callbacks") and not memory.get("guest_history"):
        return ""
    parts = []
    if memory.get("callbacks"):
        parts.append(
            "SHOW MEMORY — past episodes (LAND AT LEAST ONE CALLBACK to one of these — a bet, a title, a line — where it fits naturally):\n"
            + "\n".join(
                f"  wk{c.get('week')}: \"{c.get('title', '')}\" — {c.get('pull_quote', '')[:120]}"
                + (f" (bet: {c.get('open_bet', '')[:90]})" if c.get("open_bet") else "")
                for c in memory["callbacks"][-5:]
            )
        )
    if memory.get("guest_history"):
        parts.append("GUEST HISTORY: " + ", ".join(f"wk{g.get('week')} {g.get('name')}" for g in memory["guest_history"][-6:]))
    return "\n\n".join(parts)


def guest_voice_spec(s3, bucket, guest_id: str) -> tuple:
    """(voice_rules_json, few_shot_example) from config/coaches/<id>.json."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"config/coaches/{guest_id}.json")
        cfg = json.loads(obj["Body"].read())
        rules = json.dumps(cfg.get("structural_voice_rules") or {})[:1200]
        ex = (cfg.get("few_shot_examples") or [None])[0]
        if isinstance(ex, dict):
            ex = ex.get("output") or ex.get("text") or next(iter(ex.values()), None)
        return rules, (ex if isinstance(ex, str) else "")
    except Exception:
        return "", ""


def interleave_turns(elena_turns: list, coach_replies: list, cap: int = TURN_CAP) -> list:
    """elena[0], coach[0], elena[1], coach[1], … — pairs only, capped. Elena's
    closing line (if she has one more than the coach) stays as the sign-off."""
    turns = []
    n = min(len(elena_turns), len(coach_replies))
    for i in range(n):
        e = str(elena_turns[i].get("line", "") if isinstance(elena_turns[i], dict) else elena_turns[i]).strip()
        c = str(coach_replies[i]).strip()
        if e:
            turns.append({"speaker": "elena", "line": e})
        if c:
            turns.append({"speaker": "coach", "line": c})
    if len(elena_turns) == n + 1:
        closing = str(elena_turns[n].get("line", "") if isinstance(elena_turns[n], dict) else elena_turns[n]).strip()
        if closing:
            turns.append({"speaker": "elena", "line": closing})
    return turns[:cap]


_HARD_RULES = (
    "HARD RULES: correlative only (never causal); use ONLY numbers present in the material; hedge anything on a small sample; "
    "process over outcome — never a report-card tone; handle a hard week with compassion; never open a line with 'Matt'. "
    "NEVER mention or allude to: a death, grief, a funeral, cancer, or any named family member; any specific vice or substance; "
    "or any body weight at all — numeric OR spelled-out. Stay on training, sleep, recovery, habits, the deficit's effects, the bet, "
    "and the week's effort. Do NOT invent scenes, settings, times of day, anecdotes, or sensory detail — if it isn't in the data, "
    "it didn't happen. No AI tells: never say 'in this episode'; no tidy three-item lists; no neat bow at the end."
)


def build_weekly_script_v2(beats: dict, bible: dict, deps: dict) -> dict:
    """Two-pass episode: Elena writes HER half (voice + memory + real disputes),
    then the guest coach answers Elena's ACTUAL lines in their own voice spec.
    Same output contract as the v1 builder; {} on any failure (caller falls back)."""
    logger = deps["logger"]
    guest = beats.get("guest") or {}
    guest_id = guest.get("id", "")
    fmt = bible.get("weekly_format", {})
    memory = load_show_memory(deps["table"], deps["user_id"], logger)
    dispute = dispute_material(deps["table"], logger)
    others = [c for c in beats.get("coach_reads", []) if c["id"] != guest_id][:3]
    split_material = dispute or "\n".join(f"- {c['name']}: {c['summary']}" for c in others)

    # Pass 1 — Elena's half. She owns the structure, the bet, the title.
    elena_system = (
        f'You are Elena Voss, embedded journalist and host of "{bible.get("show_name", "The Measured Life")}". '
        "Write YOUR half of this week's episode: your opening hook, your framings and questions to the guest, and your sign-off. "
        "The guest's answers will be written separately — for each of your turns, say what you're asking or putting to them. "
        f"FORMAT:\n{json.dumps(fmt.get('segments', []))}\nSign-off line: {fmt.get('sign_off', '')}\n\n"
        f"TONE: {bible.get('tone', '')}\n\n{_HARD_RULES} "
        "If SHOW MEMORY is provided, land at least one natural callback — you remember your own show. If an AIRED DISPUTE or OPEN "
        "ARGUMENT is provided, that IS this week's Split segment — put the actual positions to the guest, don't soften them into agreement. "
        'OUTPUT ONLY JSON: {"elena_turns":[{"line":"<your words>","wants_from_guest":"<what their answer must address>"}], '
        '"open_bet":"<the one new falsifiable bet>", "last_bet_result":{"outcome":"won"|"lost"|"open"|"none"}, '
        '"pull_quote":"<one shareable line>", "episode_title":"<2-5 word hook>"}. 8-11 elena_turns (the last is your sign-off). No fences.'
    )
    _chron = beats.get("chronicle", "")
    _mem = memory_block(memory)
    # #914: a real logging stall is the week's context, not a detail to skip.
    _presence = f"{beats['presence_note']}\n\n" if beats.get("presence_note") else ""
    elena_user = (
        f"WEEK {beats.get('week')}: {beats.get('title')}.\n\n"
        + (f"CHRONICLE (background only, never quote it):\n{_chron[:3000]}\n\n" if _chron else "NO CHRONICLE THIS WEEK.\n\n")
        + _presence
        + f"GUEST: {guest.get('name')} — their recent read: {guest.get('summary', '')}\n\n"
        + f"THE SPLIT MATERIAL (real, on the record):\n{split_material}\n\n"
        + (f"{_mem}\n\n" if _mem else "")
        + f"{deps['elena_host_state']()}\n\n"
        + f"LAST WEEK'S OPEN BET (score it honestly): {beats.get('last_open_bet') or '(none)'}\n\n"
        + f"RECENT TOPICS (avoid repeating): {beats.get('recent_topics')}\n\n"
        + f"THIS WEEK'S ANGLE: {deps['episode_angle'](beats.get('week'))}\n\nWrite the JSON now."
    )
    model = deps["writer_model"]
    resp = deps["invoke"](
        {"model": model, "max_tokens": 2200, "system": elena_system, "messages": [{"role": "user", "content": elena_user}]},
        model_name=model,
    )
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    elena = deps["extract_json"](text)
    if not isinstance(elena, dict) or not isinstance(elena.get("elena_turns"), list) or len(elena["elena_turns"]) < 4:
        logger.warning("[panel] v2 pass-1 (Elena) failed — falling back to v1")
        return {}

    # Pass 2 — the guest answers Elena's ACTUAL lines, in their own voice spec.
    v_rules, v_example = guest_voice_spec(deps["s3"], deps["bucket"], guest_id)
    ask_turns = elena["elena_turns"][:-1] if len(elena["elena_turns"]) > 1 else elena["elena_turns"]
    numbered = "\n".join(
        f"{i + 1}. Elena says: \"{t.get('line', '')}\""
        + (f" (address: {t.get('wants_from_guest', '')})" if isinstance(t, dict) and t.get("wants_from_guest") else "")
        for i, t in enumerate(ask_turns)
        if isinstance(t, dict)
    )
    coach_system = (
        f"You are {guest.get('name')}, an AI coach and this week's podcast guest. Elena's actual lines are below, in order. "
        "Write YOUR reply to each — react to what she ACTUALLY said (pick up her words, push back where you disagree, answer her "
        f"questions with your real read). Stay in your own voice. {_HARD_RULES}"
        + (f"\n\nYour voice rules: {v_rules}" if v_rules else "")
        + (f"\n\nA sample in your voice:\n{v_example}" if v_example else "")
        + '\n\nOUTPUT ONLY JSON: {"replies":["<reply to line 1>", "<reply to line 2>", ...]} — exactly one reply per Elena line, in order. No fences.'
    )
    coach_user = (
        f"YOUR RECENT READ (your only data source):\n{guest.get('summary', '')}\nThemes: {', '.join(guest.get('themes', []))}\n\n"
        + (
            f"THE SPLIT MATERIAL (real positions on the record — including possibly your own):\n{split_material}\n\n"
            if split_material
            else ""
        )
        + f"ELENA'S LINES:\n{numbered}\n\nWrite the JSON now."
    )
    resp2 = deps["invoke"](
        {"model": model, "max_tokens": 2200, "system": coach_system, "messages": [{"role": "user", "content": coach_user}]},
        model_name=model,
    )
    text2 = "".join(p.get("text", "") for p in (resp2.get("content") or []) if isinstance(p, dict)).strip()
    coach = deps["extract_json"](text2)
    if not isinstance(coach, dict) or not isinstance(coach.get("replies"), list) or len(coach["replies"]) < 3:
        logger.warning("[panel] v2 pass-2 (guest) failed — falling back to v1")
        return {}

    turns = interleave_turns(elena["elena_turns"], coach["replies"])
    if len(turns) < 8:
        logger.warning("[panel] v2 interleave too short (%d) — falling back to v1", len(turns))
        return {}
    return {
        "turns": turns,
        "open_bet": elena.get("open_bet"),
        "last_bet_result": elena.get("last_bet_result"),
        "pull_quote": elena.get("pull_quote"),
        "episode_title": elena.get("episode_title"),
        "script_engine": "two-pass-v2",
    }
