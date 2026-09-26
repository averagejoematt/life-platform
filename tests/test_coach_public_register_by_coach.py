"""tests/test_coach_public_register_by_coach.py — #4213: the by-coach slots are served in
the PUBLIC register, or not at all.

#2972 guarded ONE coach-text slot (the door's `position_summary`). One click deeper,
on /coaching/by-coach/, four more slots were served to ~1,100 readers a week in the
owner register verbatim (read live from /api/coach/* on 2026-09-26 19:31Z):

  * `stance.headline_read`  — "You're still operating under significant structural load…"
  * `daily`                 — "You noticed the shift before the data confirmed it…"
  * `recent_outputs[].summary` — `key_recommendation`, an imperative to Matthew
  * `dossier.commitments[].text` (and the door's `open_actions[].text`) — `commitment_natural`

This file extends tests/test_public_audience_frame_2972.py's approach to those four
slots, through the REAL `/api/coach/{id}` handler over a `FakeDdbTable`. The live
Reeves specimens above are the fixtures: on the pre-#4213 code every serving test
below is red (the handler passed each of them through untouched).

The contract, per slot: the public twin (`public_ask` / a third-person text that
passes `audience_guard`) or an EMPTY slot — never the owner text.

Offline: no AWS, no network — FakeDdbTable + monkeypatched module globals.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from coach import (  # noqa: E402
    audience_guard,
    coach_derived_prose,
    coach_history_summarizer as chs,  # noqa: E402
)
from coach.coach_extraction_prompt import EXTRACTION_SYSTEM_PROMPT, build_extraction_message  # noqa: E402
from compute import coach_daily_reflection_lambda as daily  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as C  # noqa: E402

# ── The LIVE specimens (/api/coach/mind_coach, 2026-09-26 19:31Z) ───────────────────

_REEVES_HEADLINE = (
    "You're still operating under significant structural load—grief, protein intake sliding well short of what I "
    "suspect you need for cognitive clarity—yet you're showing up and engaging with genuine curiosity about your own "
    "signals. What's shifted in my read: the six-day journaling silence now feels like a more urgent signal than I "
    "initially weighted it."
)
_REEVES_DAILY = (
    "You noticed the shift before the data confirmed it—that matters. Your body knew something before your mind had "
    "words for it. So I'm curious: when you stopped writing, was it the kind of quiet that comes from being too "
    "depleted to reach for the pen?"
)
_REEVES_KEY_RECOMMENDATION = (
    "Reflect on whether you felt the recovery shift internally before checking the device, and distinguish which "
    "emotional texture the journaling silence carries — resistance or depletion — so we can understand what's "
    "actually blocking expression."
)
_REEVES_COMMITMENT = (
    "Reflect on whether you felt the recovery shift internally before checking the device on the night of "
    "2026-09-24, and report back on that sequence."
)

# The public register — first person for the coach, third person for Matthew, the ask reported.
_PUBLIC_HEADLINE = (
    "Matthew's body is recovering well, while his journal has been quiet. I've asked him one thing: before he picks "
    "up the phone in the morning, notice whether he already felt rested."
)
_PUBLIC_DAILY = "Matthew noticed the shift before the data confirmed it. I'm curious whether his quiet journal is tiredness or avoidance."
_PUBLIC_ASK = "I've asked him to notice, before he checks the device each morning, whether he already felt rested."

_COACH = "mind_coach"
_PK = f"COACH#{_COACH}"


# ══════════════════════════════════════════════════════════════════════════════
# The harness — the real /api/coach/{id} handler over a pk/sk-dispatching fake
# ══════════════════════════════════════════════════════════════════════════════


def _table(stance=None, outputs=(), commitments=()):
    def _query_hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        if expr.get("operator") != "AND":
            return {"Items": []}
        pk = expr["values"][0].get_expression()["values"][1]
        sk = expr["values"][1].get_expression()["values"][1]
        if pk != _PK:
            return {"Items": []}
        if sk == "OUTPUT#":
            return {"Items": [dict(o) for o in outputs]}
        if sk == "COMMITMENT#":
            return {"Items": [dict(c) for c in commitments]}
        if sk == "STANCE#" and stance:
            return {"Items": [dict(stance, sk="STANCE#2026-09-20")]}
        return {"Items": []}

    def _get_item_hook(table, key, **kw):
        if key.get("pk") == _PK and key.get("sk") == "STANCE#latest" and stance:
            return {"Item": dict(stance, pk=_PK, sk="STANCE#latest")}
        return {}

    return FakeDdbTable(query_hook=_query_hook, get_item_hook=_get_item_hook)


def _coach_body(monkeypatch, *, stance=None, outputs=(), commitments=(), daily_text=None):
    monkeypatch.setattr(C, "table", _table(stance, outputs, commitments))
    real_load = C._load_s3_json

    def _load(key, cache_name):
        if key == "generated/coach_daily.json":
            return {"reflections": {_COACH: {"text": daily_text, "date": "2026-09-26"}}} if daily_text else {}
        if key.startswith("generated/"):
            return {}
        return real_load(key, cache_name)

    monkeypatch.setattr(C, "_load_s3_json", _load)
    resp = C.handle_coach({"rawPath": f"/api/coach/{_COACH}"})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body.get("persona_id") == _COACH, body
    return body


def _stance(headline, **extra):
    base = {
        "headline_read": headline,
        "focused_on_now": ["Whether you felt the recovery spike before checking the device", "His journal's silence"],
        "set_aside_for_now": [],
        "stage": {"label": "noticing", "rationale": "He is learning to read his own signals."},
        "how_my_read_changed": "",
        "confidence_note": "",
        "as_of": "2026-09-20",
    }
    base.update(extra)
    return base


def _output(**fields):
    row = {"pk": _PK, "sk": "OUTPUT#2026-09-26#daily_brief", "content": _REEVES_DAILY, "themes": ["journaling_silence"]}
    row.update(fields)
    return row


def _commitment(**fields):
    row = {
        "pk": _PK,
        "sk": "COMMITMENT#commit_20260926_reflect",
        "created_date": "2026-09-26",
        "commitment_natural": _REEVES_COMMITMENT,
        "status": "pending",
        "due_date": "2026-10-03",
    }
    row.update(fields)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# 1. stance.headline_read (+ the rest of the stance's prose)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_reeves_headline_is_not_served(monkeypatch):
    """RED before #4213: the handler served this second-person letter verbatim."""
    body = _coach_body(monkeypatch, stance=_stance(_REEVES_HEADLINE))
    assert body["stance"]["source"] == "stance"
    assert body["stance"]["headline_read"] == ""
    for snap in body["stance_history"]:
        assert snap["headline_read"] == ""


def test_a_third_person_headline_is_served_verbatim(monkeypatch):
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE))
    assert body["stance"]["headline_read"] == _PUBLIC_HEADLINE
    assert body["stance_history"][0]["headline_read"] == _PUBLIC_HEADLINE


def test_owner_directed_stance_items_are_dropped_and_public_ones_kept(monkeypatch):
    body = _coach_body(monkeypatch, stance=_stance(_PUBLIC_HEADLINE))
    assert body["stance"]["focused_on_now"] == ["His journal's silence"]
    assert body["stance"]["stage"]["rationale"] == "He is learning to read his own signals."


# ══════════════════════════════════════════════════════════════════════════════
# 2. daily ("today's read")
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_reeves_daily_read_is_not_served(monkeypatch):
    """RED before #4213: `_coach_daily` returned the artifact's text untouched."""
    body = _coach_body(monkeypatch, daily_text=_REEVES_DAILY)
    assert body["daily"] is None


def test_a_third_person_daily_read_is_served(monkeypatch):
    body = _coach_body(monkeypatch, daily_text=_PUBLIC_DAILY)
    assert body["daily"] == _PUBLIC_DAILY


def test_the_daily_producer_gate_rejects_an_owner_directed_reflection():
    """The write side: the reflection's fail-closed gate treats a second-person text as
    a violation (retried stricter, then dropped) — and the #2889 reuse path re-gates
    through the same function, so a cached second-person reflection never republishes."""
    facts = {"allowed": set(), "allowed_dates": set(), "numbers": [], "n": 21}
    ok, reasons = daily._accepts(_REEVES_DAILY, facts, "2026-09-26")
    assert not ok and "audience_violation" in reasons
    _ok, reasons = daily._accepts(_PUBLIC_DAILY, facts, "2026-09-26")
    assert "audience_violation" not in reasons
    assert "THIRD person" in daily._SYSTEM_RULES


# ══════════════════════════════════════════════════════════════════════════════
# 3. recent_outputs[].summary (the timeline)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_key_recommendation_is_not_the_timeline_summary(monkeypatch):
    """RED before #4213: `served_summary` served `key_recommendation` (an imperative
    to Matthew), falling back to `content` (the owner narrative)."""
    body = _coach_body(monkeypatch, outputs=[_output(key_recommendation=_REEVES_KEY_RECOMMENDATION)])
    assert [o["summary"] for o in body["recent_outputs"]] == [""]


def test_the_timeline_serves_the_public_ask_first(monkeypatch):
    row = _output(key_recommendation=_REEVES_KEY_RECOMMENDATION, public_ask=_PUBLIC_ASK, public_summary=_PUBLIC_HEADLINE)
    body = _coach_body(monkeypatch, outputs=[row])
    assert body["recent_outputs"][0]["summary"] == _PUBLIC_ASK


def test_the_timeline_falls_back_to_the_public_read_never_the_owner_text(monkeypatch):
    row = _output(key_recommendation=_REEVES_KEY_RECOMMENDATION, public_ask="Log four words each morning, you know why.")
    row["public_summary"] = _PUBLIC_HEADLINE
    body = _coach_body(monkeypatch, outputs=[row])
    assert body["recent_outputs"][0]["summary"] == _PUBLIC_HEADLINE


# ══════════════════════════════════════════════════════════════════════════════
# 4. dossier.commitments[].text (feeds /api/coaching-dashboard open_actions too)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_live_commitment_imperative_is_not_served(monkeypatch):
    """RED before #4213: the dossier served `commitment_natural` verbatim."""
    body = _coach_body(monkeypatch, commitments=[_commitment()])
    commits = body["dossier"]["commitments"]
    assert len(commits) == 1, "the record itself still counts — only its text is withheld"
    assert commits[0]["text"] == ""
    assert commits[0]["date"] == "2026-09-26" and commits[0]["status"] == "pending"


def test_the_commitment_public_twin_is_served(monkeypatch):
    body = _coach_body(monkeypatch, commitments=[_commitment(public_ask=_PUBLIC_ASK)])
    assert body["dossier"]["commitments"][0]["text"] == _PUBLIC_ASK


# ══════════════════════════════════════════════════════════════════════════════
# 5. The whole page — no served slot addresses the owner
# ══════════════════════════════════════════════════════════════════════════════


def test_no_by_coach_slot_is_owner_directed_with_the_full_live_specimen_set(monkeypatch):
    """The issue's live-proof query, run offline: zero `is_owner_directed` hits across
    the four slots when every producer row is in the owner register."""
    body = _coach_body(
        monkeypatch,
        stance=_stance(_REEVES_HEADLINE),
        outputs=[_output(key_recommendation=_REEVES_KEY_RECOMMENDATION)],
        commitments=[_commitment()],
        daily_text=_REEVES_DAILY,
    )
    slots = [body["stance"]["headline_read"], body["daily"]]
    slots += [o["summary"] for o in body["recent_outputs"]]
    slots += [c["text"] for c in body["dossier"]["commitments"]]
    assert [s for s in slots if audience_guard.is_owner_directed(s)] == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. public_blurb — a SENTENCE-boundary clip, never mid-sentence (§2.3)
# ══════════════════════════════════════════════════════════════════════════════


def test_clip_keeps_whole_sentences_within_the_limit():
    s1 = "Matthew logged food on all 20 days of this attempt."
    s2 = "Friday, September 25 was a good one, with 182 g of protein and 1,761 calories."
    s3 = "I've asked him to add one vegetable serving at lunch this week, because Friday's fiber was low."
    text = f"{s1} {s2} {s3}"
    assert len(f"{s1} {s2}") <= 200 < len(text)
    assert audience_guard.clip_at_sentence(text, 200) == f"{s1} {s2}"


def test_clip_returns_short_text_unchanged_and_empty_for_nothing():
    assert audience_guard.clip_at_sentence("  Matthew slept well on Friday.  ") == "Matthew slept well on Friday."
    assert audience_guard.clip_at_sentence("") == ""
    assert audience_guard.clip_at_sentence(None) == ""


def test_clip_never_cuts_a_long_first_sentence_mid_way():
    first = (
        "Matthew's recovery averaged 74 % over the last 21 days and hit 99 % on the night of Thursday, "
        + "September 24, " * 8
        + "which is the read."
    )
    assert 200 < len(first) <= 320
    clipped = audience_guard.clip_at_sentence(first + " A second sentence follows.", 200)
    assert clipped == first


def test_clip_does_not_split_on_a_decimal_point():
    text = "His HRV was 46.8 ms on the night of Friday, September 25. " * 5
    clipped = audience_guard.clip_at_sentence(text.strip(), 200)
    assert clipped.endswith("September 25.") and "46.8 ms" in clipped


def test_public_blurb_clips_at_a_sentence_boundary():
    s1 = "Matthew logged two training sessions this week, and his recovery held at 60 % on Friday, September 25."
    s2 = "I'm watching his heart-rate variability closely, because the pattern I flagged on Day 3 hasn't moved yet."
    blurb = audience_guard.public_blurb({"public_summary": f"{s1} {s2}"}, limit=200)
    assert blurb == s1


# ══════════════════════════════════════════════════════════════════════════════
# 7. public_ask — the producer plumbing (extraction task 13 + task 11, recondense, writer)
# ══════════════════════════════════════════════════════════════════════════════


def test_public_ask_is_in_the_extraction_contract():
    assert "13. **public_ask**" in EXTRACTION_SYSTEM_PROMPT
    assert "   - public_ask:" in EXTRACTION_SYSTEM_PROMPT, "each commitment carries its own reported twin (task 11)"
    assert "public_ask." in build_extraction_message("mind_coach", "text", "daily_brief", {})


def test_public_ask_joins_the_derived_prose_set_and_the_recondense():
    assert "public_ask" in coach_derived_prose.DERIVED_PROSE_FIELDS
    assert "public_ask" not in coach_derived_prose.SERVED_SUMMARY_PREFERENCE
    assert '"public_ask"' in coach_derived_prose.RECONDENSE_SYSTEM_PROMPT
    assert coach_derived_prose.hold({"public_ask": _PUBLIC_ASK})["public_ask"] is None

    def _model(**kw):
        return {"public_ask": f"  {_PUBLIC_ASK}  ", "public_summary": _PUBLIC_HEADLINE}

    out = coach_derived_prose.recondense("mind_coach", "narrative", {"themes": ["a"]}, "fix it", _model)
    assert out["public_ask"] == _PUBLIC_ASK and out["themes"] == ["a"]


def test_public_ask_reader_seam_rejects_an_imperative_to_matthew():
    assert audience_guard.public_ask({"public_ask": _PUBLIC_ASK}) == _PUBLIC_ASK
    assert audience_guard.public_ask({"public_ask": "Log your mood before you check the app."}) is None
    assert audience_guard.public_ask({"key_recommendation": _PUBLIC_ASK}) is None, "only public_ask is ever read"
    assert audience_guard.public_ask(None) is None


def test_the_writer_persists_public_ask_through_the_guard():
    with open(os.path.join(_REPO, "lambdas", "coach", "coach_state_updater.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'audience_guard.reader_safe(extraction.get("public_ask")' in src, "OUTPUT# public_ask is written unguarded"
    assert 'audience_guard.reader_safe(c.get("public_ask")' in src, "COMMITMENT# public_ask is written unguarded"


# ══════════════════════════════════════════════════════════════════════════════
# 8. The stance producer — third person by prompt, guarded at write
# ══════════════════════════════════════════════════════════════════════════════


def test_the_stance_prompt_serves_visitors_in_the_third_person():
    assert "SERVED TO SITE VISITORS" in chs.STANCE_SYSTEM_PROMPT
    assert "Address him as 'you'" not in chs.STANCE_SYSTEM_PROMPT
    assert "my current read of you" not in chs.STANCE_SYSTEM_PROMPT


def test_write_stance_holds_an_owner_directed_headline_empty(monkeypatch):
    written = []
    monkeypatch.setattr(chs, "_put_item", lambda item: written.append(item) or True)
    assert chs._write_stance(_COACH, {"as_of": "2026-09-26", "headline_read": _REEVES_HEADLINE, "stage": {}})
    assert [w["headline_read"] for w in written] == ["", ""]
    written.clear()
    assert chs._write_stance(_COACH, {"as_of": "2026-09-26", "headline_read": _PUBLIC_HEADLINE, "stage": {}})
    assert [w["headline_read"] for w in written] == [_PUBLIC_HEADLINE, _PUBLIC_HEADLINE]
