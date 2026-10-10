"""emails/panelcast_desk.py — the Panel's Story Desk path (#4536), split out of coach_panel_podcast_lambda.py so the
god-module does not grow (#1665). When the week's chronicle was written by the Story Desk, its episode script rides on
the chronicle row; these render it through the Panel's own safety gate, voices, audio publisher, feed and series
memory. Facade state via `_g` (the module's live globals), the #1654 split shape.
"""

import json

from content import autopublish_audit, story_checks


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
        if ep and ep.get("turns"):
            # #4694: the desk's own residual findings on THIS script ride along, so the render can refuse an unaudited one
            ep["_audit_blocking"] = autopublish_audit.episode_blocking(it.get("desk_findings_json"))
            return ep
        return None
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
    # #4694: an episode script the desk left with a blocking finding (a fact, a body number, an unheld quote …) is not
    # audited, and the chronicle's approve click never showed it to anyone — HOLD it for a human, loudly (SNS names the
    # week). Absent the key (an episode handed in by another caller) there is nothing recorded to refuse on.
    unsafe += [f"audit: {f}" for f in ep.get("_audit_blocking") or []]
    if unsafe:
        if dry_run:
            return _g["_dry"](week, "HOLD", stage="desk-safety", reasons=sorted(set(unsafe)))
        return _g["_hold_and_alert"](week, sorted(set(unsafe)), {"turns": turns, "source": "story_desk"}, hold_class="safety")
    if dry_run:
        return _g["_dry"](week, "PUBLISH", stage="desk", guest=guest_name, clean_turns=len(turns), date=post.get("date"))
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
    existing = sorted([e for e in existing if e.get("week") != week] + [rec], key=lambda e: e.get("week", 0), reverse=True)
    state = _g["_state_read"]()
    _g["_state_write"](
        {
            "episode_count": len(existing),
            "last_episode": rec,
            "open_bet": (ep.get("bet") or {}).get("claim") or state.get("open_bet"),
            "recent_topics": [e["title"] for e in existing[:5]],
            "bet_ledger": state.get("bet_ledger", [])[-20:],
        }
    )
    _g["_write_indexes"](existing)
    _g["_write_show_memory"](week, rec["title"], rec["excerpt"], guest_id, guest_name, (ep.get("bet") or {}).get("claim"))
    _g["_emit_published_metric"]()
    _g["_emit_outcome"]("published")
    _g["_notify_new_episode"](rec)
    _g["logger"].info("[panel] wk%s PUBLISHED (story desk) — %d turns, guest %s", week, len(turns), guest_id)
    return {"statusCode": 200, "body": json.dumps({"week": week, "published": True, "source": "story_desk"})}
