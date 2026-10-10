"""emails/panelcast_desk.py — the Panel's Story Desk path (#4536), split out of coach_panel_podcast_lambda.py so the
god-module does not grow (#1665). When the week's chronicle was written by the Story Desk, its episode script rides on
the chronicle row; these render it through the Panel's own safety gate, voices, audio publisher, feed and series
memory. Facade state via `_g` (the module's live globals), the #1654 split shape.
"""

import json

from common import constants
from content import story_checks
from experiment.phase_filter import singleton_visible

# The season ledger's verdict vocabulary (content.story_ledger bets[].result) → the Panel scoreboard's (#4536).
_OUTCOME = {"right": "won", "wrong": "lost", "won": "won", "lost": "lost", "not_gradable": "none", "none": "none"}


def visible(item) -> dict:
    """#4536: a Panel state row the writer may read, or {} — never a restart tombstone, never another phase
    (`singleton_visible`), and never a row last written before this cycle's genesis: a previous cycle's row the reset
    did not tag would otherwise become this week's memory (the Panel scored a July bet from a cycle-5 row)."""
    if not singleton_visible(item):
        return {}
    stamp = str(item.get("updated") or item.get("updated_at") or item.get("generated_at") or "")[:10]
    return item if not stamp or stamp >= constants.EXPERIMENT_START_DATE else {}


def select_post(posts: list, week, genesis: str) -> dict:
    """`{"week": N}`: this cycle's chronicle post for week N, flagged `backfill` — an operator run for a named week
    notifies no one and never advances the series state past a later week (see `advances`)."""
    hit = [p for p in posts if str(p.get("week")) == str(week) and (p.get("date") or "") >= genesis]
    if not hit:
        raise ValueError(f"no current-cycle chronicle post for week {week}")
    return {**max(hit, key=lambda p: p["date"]), "backfill": True}


def advances(state: dict, week) -> bool:
    """The series state, the show memory and the bet ledger move only in week order: an episode for an EARLIER week
    than the last one recorded (a backfill, or a retry after a later week shipped) re-publishes its audio and its
    index row, and leaves the bet/memory record exactly as the later week left it."""
    last = (state.get("last_episode") or {}).get("week")
    return last is None or int(week) >= int(last)


def by_date(episodes: list) -> list:
    """The feed and episodes.json newest-first by air date (the week number breaks a same-day tie)."""
    return sorted(episodes, key=lambda e: (str(e.get("date") or ""), int(e.get("week") or 0)), reverse=True)


def gradable(bet) -> bool:
    """A bet is registered only with a rule code can grade — a claim, the metric it reads and the rule it applies."""
    return bool(isinstance(bet, dict) and bet.get("claim") and bet.get("metric") and bet.get("rule"))


def season_ledger(post: dict, *, _g) -> dict:
    """The season ledger this week's installment leaves (#4533): the committed LEDGER#{date} row, else the ledger the
    desk attached to the chronicle row. Read cycle-scoped through `visible`; {} when there is none."""
    pk = f"USER#{_g['USER_ID']}#SOURCE#chronicle"
    try:
        row = visible(_g["table"].get_item(Key={"pk": pk, "sk": f"LEDGER#{post.get('date')}"}).get("Item"))
        raw = row.get("ledger_json")
        if not raw:
            raw = visible(_g["table"].get_item(Key={"pk": pk, "sk": f"DATE#{post.get('date')}"}).get("Item")).get("desk_ledger_json")
        return json.loads(raw) if raw else {}
    except Exception as e:  # noqa: BLE001 — an unread ledger leaves bets open, never invents a verdict
        _g["logger"].warning("[panel] season ledger read failed — %s; bets stay open", e)
        return {}


def score_bets(bet_ledger: list, ledger: dict, week, date, new_bet) -> list:
    """The Panel scoreboard after this episode: every open bet from an earlier week takes the verdict the season ledger
    graded it with (never the writer's own say-so), then this week's bet is registered — only when it is gradable."""
    verdicts = {b.get("week"): _OUTCOME.get(str(b.get("result") or "")) for b in (ledger.get("bets") or []) if b.get("week") is not None}
    out = [dict(b) for b in bet_ledger]
    for b in out:
        verdict = verdicts.get(b.get("week"))
        if b.get("outcome") == "open" and b.get("week") != week and verdict:
            b["outcome"] = verdict
    if gradable(new_bet):
        out = [b for b in out if not (b.get("week") == week and b.get("outcome") == "open")]
        out.append({"week": week, "bet": new_bet["claim"], "outcome": "open", "date": date})
    return out[-20:]


def commit_legacy(week, ep: dict, existing: list, state: dict, script: dict, beats: dict, hook: str, guest_id: str, *, _g) -> list:
    """The legacy writer's commit (moved out of coach_panel_podcast_lambda, #4536): the episode list with this week's row,
    and — only when the week is in order (`advances`) — the series state, its bet ledger and the show memory.

    Bet ledger (the Panel scoreboard): resolve the prior open bet with THIS week's reported outcome, then record the new
    open bet. Capped, reset-safe in DDB. Idempotent per-week (2026-07-02): a RE-published episode used to (a) "resolve"
    its own week's open bet with last week's outcome and (b) append a paraphrased duplicate — the live wk1 double-bet.
    The resolve loop only touches a bet from an EARLIER week (the one the episode actually reports on), and the append
    supersedes this week's own open bet. Resolved bets are history — never touched."""
    existing = by_date([e for e in existing if e.get("week") != week] + [ep])
    if not advances(state, week):
        _g["logger"].info("[panel] wk%s is earlier than the last recorded episode — state, memory and bets left as they are", week)
        return existing
    ledger = [dict(b) for b in state.get("bet_ledger", [])]
    outcome = ((script.get("last_bet_result") or {}).get("outcome") or "open").lower()
    for entry in reversed(ledger):
        if entry.get("outcome") == "open" and entry.get("week") != week:
            entry["outcome"] = outcome if outcome in ("won", "lost", "open", "none") else "open"
            break
    if script.get("open_bet"):
        ledger = [e for e in ledger if not (e.get("week") == week and e.get("outcome") == "open")]
        ledger.append({"week": week, "bet": script["open_bet"], "outcome": "open", "date": beats["date"]})
    _g["_state_write"](
        {
            "episode_count": state.get("episode_count", 1) + 1,
            "last_episode": ep,
            "open_bet": script.get("open_bet"),
            "recent_topics": ([beats["title"]] + beats.get("recent_topics", []))[:5],
            "bet_ledger": ledger[-20:],
        }
    )
    # #547: the show remembers itself — callbacks + guest history, real records only.
    guest_name = (beats.get("guest") or {}).get("name")
    _g["_write_show_memory"](week, ep.get("title") or hook, script.get("pull_quote"), guest_id, guest_name, script.get("open_bet"))
    return existing


def door_reasons(text: str) -> list:
    """The shared reader-surface check (#4538) as a Panel hold reason: a cycle/reset/attempt count or an off-record
    specific in a spoken line holds the episode, exactly as a blocked vice does — on the desk AND the legacy writer."""
    return ["story-door"] if story_checks.reader_surface(text) else []


def door_safe(text: str) -> str:
    """A title or excerpt that fails the door is not published: the episode falls back to its bare number."""
    return "" if story_checks.reader_surface(text or "") else (text or "")


def desk_episode(post: dict, *, _g) -> dict | None:
    """The Story Desk's episode for this week's chronicle, or None (legacy path)."""
    try:
        it = _g["table"].get_item(Key={"pk": f"USER#{_g['USER_ID']}#SOURCE#chronicle", "sk": f"DATE#{post.get('date')}"}).get("Item") or {}
        raw = it.get("desk_episode_json")
        ep = json.loads(raw) if raw else None
        return ep if ep and ep.get("turns") else None
    except Exception as e:  # noqa: BLE001 — the legacy writer is the fallback, never a crash
        _g["logger"].warning("[panel] desk episode read failed — %s; using the legacy writer", e)
        return None


def publish_desk_episode(week, post: dict, ep: dict, dry_run: bool = False, *, _g) -> dict:
    """Render + publish a Story Desk episode (#4536): the same safety gate, voices, audio publisher, feed and series
    memory as the legacy path; the script itself was written and gated upstream with the chronicle."""
    from ai import gemini_tts

    guest = ep.get("guest") or {}
    guest_id = guest.get("persona_id") or guest.get("coach_id") or _g["persona_registry"].OPERATIONAL_COACH_IDS[0]
    guest_name = guest.get("name") or "Coach"
    turns = [
        {"speaker": _g["ELENA"] if t.get("speaker") == "elena" else guest_id, "line": str(t.get("line") or "").strip()} for t in ep["turns"]
    ]
    turns = [t for t in turns if t["line"]]
    unsafe = [r for t in turns for r in _g["_safety_gate"](t["line"])]
    # the title and the excerpt are reader copy too, and neither is a spoken turn (#4538)
    unsafe += door_reasons(f"{ep.get('title') or post.get('title') or ''}\n{ep.get('excerpt') or ''}")
    if unsafe:
        if dry_run:
            return _g["_dry"](week, "HOLD", stage="desk-safety", reasons=sorted(set(unsafe)))
        return _g["_hold_and_alert"](week, sorted(set(unsafe)), {"turns": turns, "source": "story_desk"}, hold_class="safety")
    state = _g["_state_read"]()
    advance = advances(state, week)
    notify = not post.get("backfill")
    if dry_run:
        return _g["_dry"](
            week,
            "PUBLISH",
            stage="desk",
            guest=guest_name,
            clean_turns=len(turns),
            date=post.get("date"),
            advance_state=advance,
            notify=notify,
        )
    label_of = {_g["ELENA"]: "Elena", guest_id: guest_name}
    voices = {"Elena": _g["_gemini_voice"](_g["ELENA"]), guest_name: _g["_gemini_voice"](guest_id)}
    label_turns = [{"speaker": label_of[t["speaker"]], "line": t["line"]} for t in turns]
    audio = gemini_tts.synthesize_dialogue(label_turns, voices, _g["WEEKLY_STYLE"])
    published = _g["_publish_episode_audio"](week, audio)
    transcript = "\n\n".join(f"{t['speaker']}: {t['line']}" for t in label_turns)
    _g["s3"].put_object(
        Bucket=_g["S3_BUCKET"],
        Key=f"{_g["PREFIX"]}/wk{week}.transcript.txt",
        Body=transcript.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    try:
        existing = json.loads(_g["s3"].get_object(Bucket=_g["S3_BUCKET"], Key=f"{_g["PREFIX"]}/episodes.json")["Body"].read()).get(
            "episodes", []
        )
    except Exception:
        existing = []
    rec = {
        "week": week,
        "title": f"EP{week} · {ep.get('title') or post.get('title')}",
        "date": post.get("date"),
        **published,
        "byline": f"Elena + {guest_name}",
        "guest_id": guest_id,
        "guest_name": guest_name,
        "excerpt": (ep.get("excerpt") or "")[:240],
        "image_url": "",
        "image_credit": "",
    }
    existing = by_date([e for e in existing if e.get("week") != week] + [rec])
    if advance:
        bets = score_bets(state.get("bet_ledger", []), season_ledger(post, _g=_g), week, post.get("date"), ep.get("bet"))
        _g["_state_write"](
            {
                "episode_count": len(existing),
                "last_episode": rec,
                "open_bet": next((b["bet"] for b in reversed(bets) if b.get("outcome") == "open"), None),
                "recent_topics": [e["title"] for e in existing[:5]],
                "bet_ledger": bets,
            }
        )
        claim = ep["bet"]["claim"] if gradable(ep.get("bet")) else None
        _g["_write_show_memory"](week, rec["title"], rec["excerpt"], guest_id, guest_name, claim)
    else:
        _g["logger"].info("[panel] wk%s is earlier than the last recorded episode — state, memory and bets left as they are", week)
    _g["_write_indexes"](existing)
    _g["_emit_published_metric"]()
    _g["_emit_outcome"]("published")
    if notify:
        _g["_notify_new_episode"](rec)
    _g["logger"].info("[panel] wk%s PUBLISHED (story desk) — %d turns, guest %s", week, len(turns), guest_id)
    return {"statusCode": 200, "body": json.dumps({"week": week, "published": True, "source": "story_desk"})}
